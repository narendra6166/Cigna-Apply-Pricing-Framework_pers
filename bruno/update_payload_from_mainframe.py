"""Update one Bruno request from a matching DATA-FROM -MAINFRAME export."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "DATA-FROM -MAINFRAME"
BRUNO_ROOT = PROJECT_ROOT / "bruno"
BODY_START = re.compile(r"body\s*:\s*json\s*\{\s*(\{)", re.IGNORECASE)


def _skip_comments_and_space(text: str, position: int) -> int:
    while position < len(text):
        if text[position].isspace():
            position += 1
        elif text[position] == "#":
            newline = text.find("\n", position)
            position = len(text) if newline == -1 else newline + 1
        else:
            break
    return position


def _balanced_object_end(text: str, start: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for position in range(start, len(text)):
        char = text[position]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return position + 1
    raise ValueError("unterminated JSON object")


def _remove_trailing_commas(text: str) -> str:
    output: list[str] = []
    in_string = False
    escaped = False
    position = 0
    while position < len(text):
        char = text[position]
        if in_string:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            position += 1
            continue
        if char == '"':
            in_string = True
            output.append(char)
        elif char == ",":
            lookahead = position + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead >= len(text) or text[lookahead] not in "}]":
                output.append(char)
        elif char.isdigit():
            end = position + 1
            while end < len(text) and text[end].isdigit():
                end += 1
            number = text[position:end]
            if len(number) > 1 and number.startswith("0") and (
                end == len(text) or text[end].isspace() or text[end] in ",}]"
            ):
                output.append(str(int(number)))
            else:
                output.append(number)
            position = end - 1
        else:
            output.append(char)
        position += 1
    return "".join(output)


def _array_balance(text: str) -> int:
    balance = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "[":
            balance += 1
        elif char == "]":
            balance -= 1
    return balance


def _comment_boundary(text: str, start: int) -> int | None:
    in_string = False
    escaped = False
    for position in range(start, len(text)):
        char = text[position]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "\n":
            line_start = position + 1
            while line_start < len(text) and text[line_start] in " \t":
                line_start += 1
            if line_start < len(text) and text[line_start] == "#":
                return line_start
    return None


def _missing_closers(text: str) -> str:
    braces = 0
    brackets = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            braces += 1
        elif char == "}":
            braces -= 1
        elif char == "[":
            brackets += 1
        elif char == "]":
            brackets -= 1
    if braces < 0 or brackets < 0:
        return ""
    return "]" * brackets + "}" * braces


def parse_export(path: Path) -> list[dict[str, Any]]:
    """Read the concatenated JSON query blocks used by the mainframe exports."""
    text = path.read_text(encoding="utf-8-sig")
    blocks: list[dict[str, Any]] = []
    position = 0
    while True:
        position = _skip_comments_and_space(text, position)
        if position >= len(text):
            break
        if text[position] != "{":
            start = text.find("{", position)
            if start == -1:
                break
            position = start
        try:
            end = _balanced_object_end(text, position)
            block_text = _remove_trailing_commas(text[position:end])
        except ValueError as error:
            boundary = _comment_boundary(text, position)
            if boundary is None:
                raise error
            truncated = text[position:boundary].rstrip()
            closers = _missing_closers(truncated)
            if not closers:
                raise error
            end = boundary
            block_text = _remove_trailing_commas(truncated + closers)
        try:
            block = json.loads(block_text)
        except json.JSONDecodeError as error:
            repaired = block_text.rstrip()
            if _array_balance(repaired) == 1 and repaired.endswith("}"):
                try:
                    block = json.loads(repaired[:-1] + "]}")
                except json.JSONDecodeError:
                    raise ValueError(f"invalid query result block: {error}") from error
            else:
                raise ValueError(f"invalid query result block: {error}") from error
        if not isinstance(block, dict):
            raise ValueError("query result block must be an object")
        blocks.append(block)
        position = end
    if not blocks:
        raise ValueError("no query result blocks found")
    return blocks


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _lookup(record: dict[str, Any], *names: str) -> Any:
    normalized = {_key(str(name)): value for name, value in record.items()}
    for name in names:
        value = normalized.get(_key(name))
        if value is not None:
            return value
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _date(value: Any) -> str | None:
    result = _text(value)
    if result and re.fullmatch(r"\d{8}", result):
        return result
    return None


def _records(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for block in blocks for rows in block.values()
            if isinstance(rows, list) for row in rows if isinstance(row, dict)]


def _query_records(blocks: list[dict[str, Any]], *query_terms: str) -> list[dict[str, Any]]:
    matches = []
    for block in blocks:
        for query, rows in block.items():
            query_text = str(query).upper()
            if all(term.upper() in query_text for term in query_terms) and isinstance(rows, list):
                matches.extend(row for row in rows if isinstance(row, dict))
    return matches


def _unique_records(records: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for record in records:
        signature = tuple(_text(_lookup(record, field)) or "" for field in fields)
        if signature not in seen:
            seen.add(signature)
            unique.append(record)
    return unique


def _service_signature(record: dict[str, Any]) -> tuple[str, ...]:
    fields = ("PROCEDURECODE", "REVENUECODE", "CHARGEAMT", "MODIFIER1", "MODIFIER2",
              "MODIFIER3", "MODIFIER4")
    values = [_text(_lookup(record, field)) or "" for field in fields]
    values.extend((_date(_lookup(record, "SERVICEFROMDATE")) or "",
                   _date(_lookup(record, "SERVICETHRUDATE")) or ""))
    return tuple(values)


def _dedupe_service_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for record in records:
        signature = _service_signature(record)
        if signature not in seen:
            seen.add(signature)
            unique.append(record)
    return unique


def _identifier(value: str) -> str:
    return _key(value)


def _payload_id(path: Path) -> str | None:
    text = path.stem
    meta = re.search(r"(?m)^\s*name:\s*(.+?)\s*$", path.read_text(encoding="utf-8"), re.IGNORECASE)
    if meta:
        text = meta.group(1).strip()
    normalized = _identifier(text)
    source_ids = {
        _source_id(source) for source in SOURCE_ROOT.rglob("*.yaml")
    }
    matching_ids = [
        source_id for source_id in source_ids
        if normalized.startswith(source_id)
        or (source_id.startswith("ap") and normalized.startswith(source_id[2:]))
    ]
    if matching_ids:
        return max(matching_ids, key=len)
    match = re.match(
        r"\s*((?:AP|OTROP|DRGOP)[-_ ]+(?:[A-Z0-9]+(?:[-_ ][A-Z0-9]+)*))",
        text,
        re.IGNORECASE,
    )
    if match:
        return _identifier(match.group(1))
    return _identifier(path.stem)


def _source_id(path: Path) -> str:
    text = path.stem
    text = re.split(r"[-_ ]+TEST DATA FROM MAINFRAME", text, flags=re.IGNORECASE)[0]
    text = text.split("—", 1)[0].split("–", 1)[0]
    return _identifier(text.strip(" -_"))


def _matching_paths(payload_name: str) -> tuple[Path, list[Path]]:
    requested = Path(payload_name.strip().strip('"').replace("\\", "/")).stem
    requested_key = _identifier(requested)
    payloads = [
        path for path in BRUNO_ROOT.rglob("*.bru")
        if path.name not in {"collection.bru", "folder.bru"}
        and _identifier(path.stem) == requested_key
    ]
    if not payloads:
        payloads = [
            path for path in BRUNO_ROOT.rglob("*.bru")
            if path.name not in {"collection.bru", "folder.bru"}
            and _payload_id(path) == requested_key
        ]
    if not payloads:
        raise ValueError(f"no Bruno payload matches '{payload_name}'")
    if len(payloads) != 1:
        choices = ", ".join(str(path.relative_to(BRUNO_ROOT)) for path in payloads)
        raise ValueError(f"payload name is ambiguous; choose its full filename: {choices}")
    payload = payloads[0]
    payload_id = _payload_id(payload)
    sources = [
        path for path in SOURCE_ROOT.rglob("*.yaml")
        if _source_id(path) == payload_id
    ]
    if not sources:
        raise ValueError(
            f"no mainframe source matches scenario '{payload_id}' for "
            f"{payload.relative_to(BRUNO_ROOT)}"
        )
    return payload, sorted(sources)


def _choose_source(sources: list[Path], input_fn=input, output_fn=print) -> Path:
    if len(sources) == 1:
        return sources[0]
    output_fn("More than one mainframe source matches. Choose the source file:")
    for index, source in enumerate(sources, 1):
        output_fn(f"  {index}. {source.relative_to(SOURCE_ROOT)}")
    while True:
        choice = input_fn("Source number: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(sources):
            return sources[int(choice) - 1]
        output_fn(f"Enter a number from 1 to {len(sources)}.")


def _set_if_existing(target: dict[str, Any], field: str, value: Any) -> None:
    if field in target and value is not None:
        target[field] = value


def _update_code_list(target: Any, value: Any, item_key: str) -> Any:
    if not isinstance(target, list):
        return target
    values = [part.strip() for part in (_text(value) or "").split(",")]
    updated = copy.deepcopy(target)
    for index, item in enumerate(updated):
        if isinstance(item, dict) and item_key in item:
            item[item_key] = values[index] if index < len(values) else ""
    return updated


def update_request(request: dict[str, Any], blocks: list[dict[str, Any]]) -> tuple[int, int]:
    rows = _records(blocks)
    claim_rows = _query_records(blocks, "P20_GCDOC_NO", "EMPLOYEESSN") or rows
    header = next(
        (row for row in claim_rows if _lookup(row, "P20_GCDOC_NO") is not None
         and _lookup(row, "EMPLOYEESSN") is not None),
        None,
    )
    if header is None:
        raise ValueError("source does not contain a claim/member result row")

    member = request.get("memberInformation")
    plan = request.get("planInformation")
    providers = request.get("providers")
    claim_info = request.get("claimInformation")
    if not all(isinstance(value, dict) for value in (member, plan, providers, claim_info)):
        raise ValueError("payload does not match the expected request structure")
    claim = claim_info.get("claimLevel")
    service_level = claim_info.get("serviceLevel")
    if not isinstance(claim, dict) or not isinstance(service_level, list):
        raise ValueError("payload is missing claimLevel or serviceLevel")
    pricing = claim.get("pricingDetails")
    if not isinstance(pricing, dict):
        raise ValueError("payload is missing claimLevel.pricingDetails")
    doc_number = _text(_lookup(header, "P20_GCDOC_NO"))

    header_map = (
        (member, "employeeSsn", ("EMPLOYEESSN",)),
        (member, "subscriberPid", ("SUBSCRIBERPID",)),
        (member, "patientPid", ("PATIENTPID",)),
        (member, "patientDob", ("PATIENTDOB",)),
        (plan, "soc", ("SOC",)),
        (plan, "clientId", ("CLIENTID",)),
        (plan, "accountNumber", ("ACCOUNTNUMBER",)),
        (plan, "benopt", ("BENOPT",)),
        (providers, "providerTin", ("PROVIDERTIN",)),
        (providers, "renderingCpfId", ("RENDERINGCPFID",)),
        (providers, "billingCpfId", ("BILLINGCPFID",)),
        (providers, "renderingProviderType", ("RENDERINGPROVIDERTYPE",)),
        (providers, "zipCode", ("ZIPCODE",)),
    )
    for target, field, aliases in header_map:
        value = _text(_lookup(header, *aliases))
        if value is not None and field in target:
            if field == "patientDob":
                value = _date(value) or value
            target[field] = value

    suffix = _text(_lookup(header, "PATIENTSUFFIX"))
    _set_if_existing(member, "patientSuffix", suffix.zfill(2) if suffix else None)
    _set_if_existing(request, "requestDate", _date(_lookup(header, "REQUESTDATE")))
    _set_if_existing(claim, "claimReceiveDate", _date(_lookup(header, "REQUESTDATE")))
    _set_if_existing(claim, "formType", _text(_lookup(header, "FORM_TYPE")))
    _set_if_existing(plan, "planSchedule", _text(_lookup(header, "SCHEDULEATTR")))

    existing_key = _text(claim.get("claimCcrKey")) or ""
    key_suffix = existing_key.split("_", 1)[1] if "_" in existing_key else ""
    if doc_number:
        _set_if_existing(
            claim, "claimCcrKey",
            f"{doc_number}_{key_suffix}" if key_suffix else doc_number,
        )
        reference = _text(request.get("serviceReferenceId")) or ""
        prefix = reference.split("_", 1)[0] if "_" in reference else "ApplyPricing"
        prefix = re.sub(r"[-_]\d{8,}$", "", prefix)
        _set_if_existing(
            request, "serviceReferenceId",
            f"{prefix}_{doc_number}_{key_suffix}" if key_suffix else f"{prefix}_{doc_number}",
        )

    pricing_rows = _unique_records(
        [row for row in (_query_records(blocks, "GRP_CHG", "ALLOW_CHG") or rows)
         if _lookup(row, "ALLOW_CHG", "SANP_CL_ALLOW_CHG") is not None
         and _lookup(row, "GRP_CHG") is not None],
        ("GRP_CHG", "ALLOW_CHG", "USAGE", "RATETYPE", "BASED_ON", "BASEDON_CD", "APC_NUM"),
    )
    service_rows = _dedupe_service_rows(
        [row for row in (_query_records(blocks, "SERVICEFROMDATE") or rows)
         if _lookup(row, "PROCEDURECODE") is not None]
    )
    service_rows = [row for row in service_rows if _text(_lookup(row, "PROCEDURECODE"))]
    if not service_rows:
        raise ValueError("source contains no service-line details; payload was not changed")
    diagnosis = next(
        (_text(_lookup(row, "P20_GCDOC_DIAG_CODE", "DIAG_CODE"))
         for row in (_query_records(blocks, "DIAG_CODE") or rows)
         if _text(_lookup(row, "P20_GCDOC_DIAG_CODE", "DIAG_CODE"))),
        None,
    )
    _set_if_existing(
        claim, "claimPrimaryDiagnosisCode", diagnosis.rstrip() if diagnosis else None
    )

    updated_lines = 0
    if isinstance(service_level, list) and service_rows:
        if not service_level:
            raise ValueError("cannot rebuild service lines because the payload has no line template")
        old_lines = service_level
        rebuilt_lines = []
        for index, source_line in enumerate(service_rows):
            target_line = copy.deepcopy(old_lines[min(index, len(old_lines) - 1)])
            if not isinstance(target_line, dict):
                continue
            line_map = (
                ("serviceFromDate", ("SERVICEFROMDATE",), _date),
                ("serviceThruDate", ("SERVICETHRUDATE",), _date),
                ("procedureCode", ("PROCEDURECODE",), _text),
                ("chargeAmt", ("CHARGEAMT",), lambda value: value),
                ("modifier1", ("MODIFIER1",), lambda value: _text(value) or ""),
                ("modifier2", ("MODIFIER2",), lambda value: _text(value) or ""),
                ("modifier3", ("MODIFIER3",), lambda value: _text(value) or ""),
                ("modifier4", ("MODIFIER4",), lambda value: _text(value) or ""),
                ("placeOfService", ("PLACEOFSERVICE",), _text),
                ("pathwellSpecialityCode", ("PATHWELLSPECIALITYCODE",), _text),
                ("enhancementCode", ("ENHANCEMENTCODE",), _text),
            )
            for field, aliases, converter in line_map:
                value = converter(_lookup(source_line, *aliases))
                if value is not None and field in target_line:
                    target_line[field] = value
            revenue = _lookup(source_line, "REVENUECODE")
            if revenue is not None and "revenueCode" in target_line:
                try:
                    target_line["revenueCode"] = str(abs(int(revenue))).zfill(5)
                except (TypeError, ValueError):
                    pass
            if diagnosis and "diagnosisCode" in target_line:
                target_line["diagnosisCode"] = diagnosis.rstrip()
            _set_if_existing(target_line, "lineNum", f"{index + 1:04d}")
            area = target_line.get("pricingArea")
            if isinstance(area, dict):
                _set_if_existing(area, "pdLineNum", index + 1)
                _set_if_existing(area, "pdPtr", index + 1)
            if index < len(pricing_rows):
                detail = pricing_rows[index]
                for field, aliases in (
                    ("pdAllowed", ("ALLOW_CHG", "SANP_CL_ALLOW_CHG")),
                    ("pdGroupCharge", ("GRP_CHG",)),
                    ("pdMaxUnits", ("MAX_UNITS",)),
                    ("pdApcNum", ("APC_NUM",)),
                ):
                    if isinstance(area, dict):
                        _set_if_existing(area, field, _lookup(detail, *aliases))
                updated_lines += 1
            rebuilt_lines.append(target_line)
        claim_info["serviceLevel"] = rebuilt_lines

    if service_rows:
        old_rules = pricing.get("pricingRules")
        if not isinstance(old_rules, list) or not old_rules:
            raise ValueError("cannot rebuild pricingRules because the payload has no rule template")
        rebuilt_rules = []
        allowed_total = 0.0
        all_amounts_available = len(pricing_rows) == len(service_rows)
        for index in range(len(service_rows)):
            rule = copy.deepcopy(old_rules[min(index, len(old_rules) - 1)])
            if not isinstance(rule, dict):
                continue
            if index < len(pricing_rows):
                detail = pricing_rows[index]
                based_on = _lookup(detail, "BASED_ON", "BASEDON_CD")
                rate_type = _lookup(detail, "RATETYPE")
                usage = _text(_lookup(detail, "USAGE"))
                if based_on is not None:
                    if "pdBasedonCd" in rule:
                        rule["pdBasedonCd"] = _update_code_list(
                            rule["pdBasedonCd"], based_on, "pdBasedonCode"
                        )
                if rate_type is not None:
                    if "pdRateTypeCd" in rule:
                        rule["pdRateTypeCd"] = _update_code_list(
                            rule["pdRateTypeCd"], rate_type, "pdRateTypeCode"
                        )
                _set_if_existing(rule, "pdUsage", usage)
                amount = _lookup(detail, "ALLOW_CHG", "SANP_CL_ALLOW_CHG")
                if isinstance(amount, (int, float)):
                    allowed_total += amount
                else:
                    all_amounts_available = False
            _set_if_existing(rule, "pdLineNum", index + 1)
            _set_if_existing(rule, "pdOriginalLineNum", index + 1)
            rebuilt_rules.append(rule)
        pricing["pricingRules"] = rebuilt_rules
        if all_amounts_available and "allowedCharges" in pricing:
            pricing["allowedCharges"] = round(allowed_total, 2)
        pricer = _text(_lookup(header, "PRICINGTYPE"))
        pricer_types = {"APC": "I", "ASC": "64", "DRG": "S"}
        if pricer and pricer.upper() in pricer_types and "pricerType" in pricing:
            pricing["pricerType"] = pricer_types[pricer.upper()]
        _set_if_existing(
            pricing, "usedDrgCode",
            (_text(_lookup(header, "USEDDRG")) or "").strip() or None,
        )
        _set_if_existing(pricing, "groupVersion", _text(_lookup(header, "DRGVERSION")))

    network = claim_info.get("serviceLevel", [])
    for line in network if isinstance(network, list) else []:
        area = line.get("networkArea") if isinstance(line, dict) else None
        if not isinstance(area, dict):
            continue
        for field, aliases in (
            ("networkId", ("NETWORKID",)),
            ("claimEngineNetworkId", ("CLAIMENGINENETWORKID",)),
            ("providerNetworkIndicator", ("PROVIDERNETWORKINDICATOR",)),
            ("ccnIndicator", ("CCNINDICATOR",)),
            ("mmmIndicator", ("MMMINDICATOR",)),
        ):
            value = _text(_lookup(header, *aliases))
            _set_if_existing(area, field, value)

    return updated_lines, len(service_rows)


def update_payload(payload_path: Path, source_path: Path) -> tuple[int, int]:
    text = payload_path.read_text(encoding="utf-8")
    match = BODY_START.search(text)
    if not match:
        raise ValueError(f"{payload_path.name} does not contain a body:json request")
    body_start = match.start(1)
    body_end = _balanced_object_end(text, body_start)
    try:
        request = json.loads(_remove_trailing_commas(text[body_start:body_end]))
    except json.JSONDecodeError as error:
        raise ValueError(f"cannot parse request body in {payload_path.name}: {error}") from error
    changed = update_request(request, parse_export(source_path))
    body = json.dumps(request, indent=2, ensure_ascii=False)
    payload_path.write_text(text[:body_start] + body + text[body_end:], encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", required=True, help="Bruno payload name, scenario ID, or .bru filename")
    args = parser.parse_args(argv)
    try:
        payload, sources = _matching_paths(args.payload)
        source = _choose_source(sources)
        lines_updated, source_line_count = update_payload(payload, source)
    except (OSError, ValueError) as error:
        print(f"Payload update failed: {error}", file=sys.stderr)
        return 1
    print(f"Updated {payload.relative_to(BRUNO_ROOT)} from {source.relative_to(SOURCE_ROOT)}.")
    print(f"Mapped {lines_updated} pricing lines; found {source_line_count} service lines.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
