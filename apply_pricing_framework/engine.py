"""Evaluate saved Bruno results against configurable scenario rules."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


class CatalogError(ValueError):
    """The scenario catalog is incomplete or malformed."""


CONDITION_OPS = {
    "pricing_status_in",
    "pricing_status_not_in",
    "pricer_type_equals",
    "group_method_equals",
    "ovrag_cfg_equals",
    "service_line_count_min",
    "service_line_count_equals",
    "line_relation_present",
    "line_relations_include",
    "denied_zero_allowed_line_present",
    "pricing_rule_present",
    "pricing_rule_absent",
    "used_drg_present",
    "included_line_count_min",
    "excluded_line_count_min",
    "included_allowed_relation",
    "service_lines_have_pricing_area",
    "no_service_procedure_type",
    "pricing_details_present",
    "service_line_missing_pricing_area",
    "total_allowed_is_zero",
    "denied_rate_type_present",
    "numeric_rate_type_present",
    "numeric_rate_type_absent",
    "ppo_disc_reason_equals",
    "request_excess_present",
    "pricing_basedon_present",
    "plan_limit_relation_present",
    "plan_limit_unlimited_present",
    "group_allowed_gt_included_billed",
}
CHECK_OPS = {
    "response_message_code_in",
    "response_group_method_equals",
    "any_service_line_code_in",
    "no_service_line_code_in",
    "all_source_line_codes_in",
    "success_service_line_present",
    "priced_line_with_positive_allowed_present",
    "response_line_id_absent",
    "response_line_id_present",
    "over_allowed_lines_return_code",
    "direct_amounts_reconcile",
    "grouped_amounts_reconcile",
    "rnc_present",
    "rnc_matches_request_ppo_disc_reason",
    "response_text_contains",
    "claim_excess_positive",
    "case_rate_amounts_reconcile",
}


def load_catalog(path: Path) -> dict[str, Any]:
    catalog = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(catalog, dict):
        raise CatalogError("Catalog root must be a JSON object")
    if catalog.get("schema_version") != 1:
        raise CatalogError("Unsupported scenario catalog version")
    scenarios = catalog.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise CatalogError("Catalog must contain a non-empty scenarios array")
    seen: set[str] = set()
    seen_payloads: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise CatalogError("Every scenario must be a JSON object")
        for field in ("id", "name", "category", "expected", "conditions", "checks", "design_refs"):
            if field not in scenario:
                raise CatalogError(f"Scenario is missing {field!r}")
        if not all(isinstance(scenario[field], str) and scenario[field].strip() for field in ("id", "name", "category", "expected")):
            raise CatalogError("Scenario id, name, category, and expected must be non-empty strings")
        if scenario["id"].strip() in seen:
            raise CatalogError(f"Duplicate scenario ID: {scenario['id']}")
        seen.add(scenario["id"].strip())
        if not isinstance(scenario.get("payloads"), list):
            raise CatalogError(f"{scenario['id']}: payloads must be an array")
        for payload in scenario["payloads"]:
            if not isinstance(payload, str) or not payload.strip():
                raise CatalogError(f"{scenario['id']}: payload mappings must be non-empty strings")
            key = payload.replace("\\", "/").casefold()
            if key in seen_payloads:
                raise CatalogError(f"Payload is mapped to more than one scenario: {payload}")
            seen_payloads.add(key)
        if not isinstance(scenario["conditions"], list) or not isinstance(scenario["checks"], list):
            raise CatalogError(f"{scenario['id']}: conditions and checks must be arrays")
        for condition in scenario["conditions"]:
            if not isinstance(condition, dict) or condition.get("op") not in CONDITION_OPS:
                raise CatalogError(f"{scenario['id']}: unsupported condition {condition!r}")
        for check in scenario["checks"]:
            if not isinstance(check, dict) or check.get("op") not in CHECK_OPS:
                raise CatalogError(f"{scenario['id']}: unsupported expected-result check {check!r}")
            if check.get("severity", "critical") not in {"critical", "partial"}:
                raise CatalogError(f"{scenario['id']}: check severity must be critical or partial")
        if not isinstance(scenario["design_refs"], list) or not all(
            isinstance(item, str) and item.strip() for item in scenario["design_refs"]
        ):
            raise CatalogError(f"{scenario['id']}: design_refs must be non-empty strings")
        if scenario.get("readiness", "ready") not in {"ready", "conditional", "design_pending"}:
            raise CatalogError(f"{scenario['id']}: unsupported readiness value")
        if not scenario["checks"] and scenario.get("readiness", "ready") != "design_pending":
            raise CatalogError(f"{scenario['id']}: runnable scenario must have at least one check")
        if scenario.get("readiness") == "conditional" and not isinstance(scenario.get("activation"), dict):
            raise CatalogError(f"{scenario['id']}: conditional scenario needs activation criteria")
        if scenario.get("readiness") == "conditional" and scenario["activation"].get("op") not in CHECK_OPS:
            raise CatalogError(f"{scenario['id']}: unsupported conditional activation check")
    return catalog


def _body(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def load_results(paths: list[Path]) -> list[dict[str, Any]]:
    """Read Bruno's reporter JSON and remove exact duplicates across merge inputs."""
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Bruno result file not found: {path}")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        batches = data if isinstance(data, list) else [data] if isinstance(data, dict) else None
        if batches is None:
            raise ValueError(f"Unexpected Bruno JSON reporter format: {path}")
        for batch in batches:
            if not isinstance(batch, dict):
                continue
            for result in batch.get("results", []):
                identity = json.dumps(
                    [
                        result_filename(result),
                        (result.get("request") or {}).get("data"),
                        (result.get("response") or {}).get("data"),
                    ],
                    sort_keys=True,
                    default=str,
                )
                if identity in seen:
                    continue
                seen.add(identity)
                results.append(result)
    return results


def result_filename(result: dict[str, Any]) -> str:
    test = result.get("test")
    return str((test.get("filename") if isinstance(test, dict) else "") or result.get("path") or "")


def match_payload(filename: str, scenario: dict[str, Any]) -> bool:
    normalized = filename.replace("\\", "/").lower()
    return any(
        normalized.endswith(payload.replace("\\", "/").lower())
        for payload in scenario.get("payloads", [])
    )


def request_body(result: dict[str, Any]) -> dict[str, Any] | None:
    request = result.get("request")
    return _body(request.get("data")) if isinstance(request, dict) else None


def response_body(result: dict[str, Any]) -> dict[str, Any] | None:
    response = result.get("response")
    return _body(response.get("data")) if isinstance(response, dict) else None


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _line_id(value: Any) -> str:
    text = str(value).strip()
    if text.isdigit():
        return text.lstrip("0") or "0"
    return text.upper()


def _is_true(value: Any) -> bool:
    return value is True or str(value).strip().upper() in {"Y", "YES", "TRUE", "1"}


def _is_unlimited_limit(value: Any) -> bool:
    text = str(value).strip()
    digits = text.replace(".", "")
    return len(digits) >= 2 and all(character == "9" for character in digits)


def _is_excluded(line: dict[str, Any]) -> bool:
    pricing = line.get("pricingArea")
    return isinstance(pricing, dict) and _is_true(pricing.get("clExcluded"))


def _request_parts(request: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    claim = request.get("claimInformation")
    claim = claim if isinstance(claim, dict) else {}
    claim_level = claim.get("claimLevel")
    claim_level = claim_level if isinstance(claim_level, dict) else {}
    pricing = claim_level.get("pricingDetails")
    pricing = pricing if isinstance(pricing, dict) else {}
    services = claim.get("serviceLevel")
    services = [line for line in services if isinstance(line, dict)] if isinstance(services, list) else []
    return claim_level, pricing, services


def _rate_types(pricing: dict[str, Any]) -> list[str]:
    output: list[str] = []
    for rule in pricing.get("pricingRules") or []:
        if not isinstance(rule, dict):
            continue
        for item in rule.get("pdRateTypeCd") or []:
            value = item.get("pdRateTypeCode") if isinstance(item, dict) else item
            if value is not None:
                output.append(str(value))
    return output


def _pricing_rule_exists(pricing: dict[str, Any], line_num: Any, usages: list[str]) -> bool:
    expected_line = _decimal(line_num)
    for rule in pricing.get("pricingRules") or []:
        if not isinstance(rule, dict):
            continue
        actual_line = _decimal(rule.get("pdLineNum"))
        usage = str(rule.get("pdUsage") or "").strip().upper()
        if actual_line == expected_line and usage in {str(value).upper() for value in usages}:
            return True
    return False


def _line_amount(line: dict[str, Any]) -> tuple[Decimal, Decimal] | None:
    pricing_area = line.get("pricingArea")
    if not isinstance(pricing_area, dict):
        return None
    billed = _decimal(line.get("chargeAmt"))
    allowed = _decimal(pricing_area.get("pdAllowed"))
    if billed is None or allowed is None:
        return None
    return billed, allowed


def _line_relation(line: dict[str, Any]) -> str | None:
    amounts = _line_amount(line)
    if amounts is None:
        return None
    billed, allowed = amounts
    if allowed < billed:
        return "allowed_lt_billed"
    if allowed > billed:
        return "allowed_gt_billed"
    return "allowed_eq_billed"


def _numeric_codes(pricing: dict[str, Any]) -> list[str]:
    codes = []
    for value in _rate_types(pricing):
        codes.extend(re.findall(r"(?<!\d)(\d{3})(?!\d)", value))
    return codes


def _response_lines(response: dict[str, Any]) -> list[dict[str, Any]]:
    lines = response.get("lineItems")
    return [line for line in lines if isinstance(line, dict)] if isinstance(lines, list) else []


def _line_message_code(line: dict[str, Any]) -> str:
    message = line.get("message")
    return str(message.get("code") or "") if isinstance(message, dict) else ""


def _response_line_map(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        _line_id(line.get("lineNumber")): line
        for line in _response_lines(response)
        if line.get("lineNumber") is not None
    }


def _precondition(
    check: dict[str, Any], request: dict[str, Any], response: dict[str, Any] | None
) -> tuple[bool, str]:
    claim, pricing, services = _request_parts(request)
    op = check["op"]
    value = check.get("value")
    if op == "pricing_status_in":
        passed = pricing.get("pricingStatus") in check["values"] or str(pricing.get("pricingStatus")) in {
            str(item) for item in check["values"]
        }
        return passed, f"pricingStatus must be one of {check['values']}; got {pricing.get('pricingStatus')!r}"
    if op == "pricing_status_not_in":
        passed = pricing.get("pricingStatus") not in check["values"] and str(pricing.get("pricingStatus")) not in {
            str(item) for item in check["values"]
        }
        return passed, f"pricingStatus must not be one of {check['values']}; got {pricing.get('pricingStatus')!r}"
    if op == "pricer_type_equals":
        passed = str(pricing.get("pricerType") or "").strip() == str(value)
        return passed, f"pricerType must be {value!r}; got {pricing.get('pricerType')!r}"
    if op == "group_method_equals":
        passed = str(pricing.get("groupMethod") or "").strip() == str(value)
        return passed, f"groupMethod must be {value!r}; got {pricing.get('groupMethod')!r}"
    if op == "ovrag_cfg_equals":
        passed = str(pricing.get("ovragCfg") or "").strip().upper() == str(value).upper()
        return passed, f"ovragCfg must be {value!r}; got {pricing.get('ovragCfg')!r}"
    if op == "service_line_count_min":
        passed = len(services) >= int(value)
        return passed, f"expected at least {value} source lines; got {len(services)}"
    if op == "service_line_count_equals":
        passed = len(services) == int(value)
        return passed, f"expected {value} source lines; got {len(services)}"
    if op == "line_relation_present":
        actual = sorted({relation for line in services if (relation := _line_relation(line))})
        passed = value in actual
        return passed, f"expected a line with {value}; found {actual or 'no complete line amounts'}"
    if op == "line_relations_include":
        actual = {relation for line in services if (relation := _line_relation(line))}
        missing = [relation for relation in check["values"] if relation not in actual]
        return not missing, f"missing required line relationships {missing}; found {sorted(actual)}"
    if op == "denied_zero_allowed_line_present":
        denied = any("DENIED" in item.upper() for item in _rate_types(pricing))
        zero_line = any(
            (amounts := _line_amount(line)) is not None and amounts[1] == 0
            for line in services
        )
        passed = denied and zero_line
        return passed, f"expected a zero-allowed denied line; denied={denied}, zero_allowed={zero_line}"
    if op == "pricing_rule_present":
        passed = _pricing_rule_exists(pricing, check["line_num"], check["usages"])
        return passed, f"expected pricing detail line {check['line_num']} with usage {check['usages']}"
    if op == "pricing_rule_absent":
        passed = not _pricing_rule_exists(pricing, check["line_num"], check["usages"])
        return passed, f"pricing detail line {check['line_num']} with usage {check['usages']} must be absent"
    if op == "used_drg_present":
        used = str(pricing.get("usedDrgCode") or pricing.get("usedDrg") or "").strip()
        passed = bool(used) is bool(value)
        return passed, f"UsedDRG expected {'populated' if value else 'blank'}; got {used or '<blank>'}"
    if op == "included_line_count_min":
        count = sum(1 for line in services if not _is_excluded(line))
        passed = count >= int(value)
        return passed, f"expected at least {value} included lines; got {count}"
    if op == "excluded_line_count_min":
        count = sum(1 for line in services if _is_excluded(line))
        passed = count >= int(value)
        return passed, f"expected at least {value} excluded lines; got {count}"
    if op == "included_allowed_relation":
        amounts = [_line_amount(line) for line in services if not _is_excluded(line)]
        complete = [item for item in amounts if item is not None]
        billed = sum((item[0] for item in complete), Decimal("0"))
        allowed = sum((item[1] for item in complete), Decimal("0"))
        relation = "lt_billed" if allowed < billed else "gt_billed" if allowed > billed else "eq_billed"
        passed = len(complete) > 0 and relation == value
        return passed, f"included allowed total {allowed} must be {value} relative to billed total {billed}"
    if op == "service_lines_have_pricing_area":
        has_area = bool(services) and all(isinstance(line.get("pricingArea"), dict) for line in services)
        passed = has_area is bool(value)
        return passed, f"service pricingArea presence expected {value}; got {has_area}"
    if op == "no_service_procedure_type":
        found = [
            str(line.get("procedureCodeType") or "").strip().upper()
            for line in services
            if str(line.get("procedureCodeType") or "").strip().upper() in {str(x).upper() for x in check["values"]}
        ]
        return not found, f"procedure types {found} must be absent"
    if op == "pricing_details_present":
        present = isinstance(claim.get("pricingDetails"), dict)
        return present is bool(value), f"pricingDetails presence expected {value}; got {present}"
    if op == "service_line_missing_pricing_area":
        missing = any(not isinstance(line.get("pricingArea"), dict) for line in services)
        return missing is bool(value), f"missing pricingArea expected {value}; got {missing}"
    if op == "total_allowed_is_zero":
        amounts = [_line_amount(line) for line in services]
        complete = [amount for amount in amounts if amount is not None]
        total = sum((amount[1] for amount in complete), Decimal("0"))
        passed = bool(complete) and (total == 0) is bool(value)
        return passed, f"total line allowed is {total}; zero expected={value}"
    if op == "denied_rate_type_present":
        found = any("DENIED" in item.upper() for item in _rate_types(pricing))
        return found is bool(value), f"Denied rate type expected {value}; got {found}"
    if op == "numeric_rate_type_present":
        passed = str(value) in _numeric_codes(pricing)
        return passed, f"numeric rate type {value} expected; found {_numeric_codes(pricing)}"
    if op == "numeric_rate_type_absent":
        found = _numeric_codes(pricing)
        return (not found) is bool(value), f"numeric rate types expected absent={value}; found {found}"
    if op == "ppo_disc_reason_equals":
        passed = str(pricing.get("ppoDiscReason")) == str(value)
        return passed, f"ppoDiscReason must be {value}; got {pricing.get('ppoDiscReason')!r}"
    if op == "request_excess_present":
        excess = any(
            (amounts := _line_amount(line)) is not None and amounts[1] > amounts[0]
            for line in services
        )
        return excess is bool(value), f"request allowed-over-billed line expected={value}; got {excess}"
    if op == "pricing_basedon_present":
        wanted = {str(item).strip().upper().removeprefix("SI-") for item in check["values"]}
        found = {
            str(item.get("pdBasedonCode") or "").strip().upper().removeprefix("SI-")
            for rule in pricing.get("pricingRules") or []
            if isinstance(rule, dict)
            for item in rule.get("pdBasedonCd") or []
            if isinstance(item, dict)
        }
        matched = sorted(wanted.intersection(found))
        return bool(matched), f"expected based-on code in {sorted(wanted)}; found {sorted(found)}"
    if op == "plan_limit_relation_present":
        found = []
        for line in services:
            billed = _decimal(line.get("chargeAmt"))
            limit = _decimal(line.get("planCoveredExpenseLimit"))
            if billed is None or limit is None or _is_unlimited_limit(line.get("planCoveredExpenseLimit")):
                continue
            relation = "lt_billed" if limit < billed else "gt_billed" if limit > billed else "eq_billed"
            found.append(relation)
        return value in found, f"expected a finite plan limit {value} relative to billed; found {found or 'no finite line limits'}"
    if op == "plan_limit_unlimited_present":
        found = any(
            _is_unlimited_limit(line.get("planCoveredExpenseLimit"))
            for line in services
            if line.get("planCoveredExpenseLimit") is not None
        )
        return found is bool(value), f"unlimited all-9s plan limit expected={value}; got {found}"
    if op == "group_allowed_gt_included_billed":
        allowed = _decimal(pricing.get("allowedCharges"))
        billed_values = [
            _line_amount(line)[0]
            for line in services
            if not _is_excluded(line) and _line_amount(line) is not None
        ]
        billed_total = sum(billed_values, Decimal("0"))
        passed = allowed is not None and billed_total > 0 and allowed > billed_total
        expected = bool(value)
        return passed is expected, (
            f"group allowedCharges {allowed} {'must exceed' if expected else 'must not exceed'} "
            f"included billed total {billed_total}"
        )
    return False, f"unsupported precondition operation {op!r}"


def _json_values(value: Any, path: str) -> list[Any]:
    current = [value]
    if not path:
        return current
    for part in path.split("."):
        wildcard = part.endswith("[*]")
        key = part[:-3] if wildcard else part
        next_items: list[Any] = []
        for item in current:
            candidate = item.get(key) if isinstance(item, dict) else None
            if wildcard:
                if isinstance(candidate, list):
                    next_items.extend(candidate)
            elif candidate is not None:
                next_items.append(candidate)
        current = next_items
    return current


def _comparison(
    check: dict[str, Any], request: dict[str, Any], response: dict[str, Any]
) -> tuple[bool, str]:
    _, pricing, services = _request_parts(request)
    claim = response.get("claimLevel") if isinstance(response.get("claimLevel"), dict) else {}
    lines = _response_lines(response)
    codes = [_line_message_code(line) for line in lines]
    op = check["op"]
    values = [str(value) for value in check.get("values", [])]

    if op == "response_message_code_in":
        message = response.get("message") if isinstance(response.get("message"), dict) else {}
        actual = str(message.get("code") or "")
        return actual in values, f"claim message code expected one of {values}; got {actual or '<missing>'}"
    if op == "response_group_method_equals":
        actual = str(claim.get("claimLevelGroupMethod") or "")
        return actual == check["value"], f"claim group method expected {check['value']}; got {actual or '<missing>'}"
    if op == "any_service_line_code_in":
        found = sorted(set(codes).intersection(values))
        return bool(found), f"expected a service-line message code in {values}; got {codes}"
    if op == "no_service_line_code_in":
        found = sorted(set(codes).intersection(values))
        return not found, f"expected no service-line message code in {values}; got {found or codes}"
    if op == "all_source_line_codes_in":
        output = _response_line_map(response)
        missing = []
        for line in services:
            identifier = _line_id(line.get("lineNum"))
            actual = output.get(identifier)
            if actual is None:
                missing.append(f"{identifier}: missing response line")
            elif _line_message_code(actual) not in values:
                missing.append(f"{identifier}: expected code in {values}, got {_line_message_code(actual)}")
        return not missing and bool(services), "; ".join(missing) or f"all {len(services)} source lines returned codes in {values}"
    if op == "success_service_line_present":
        found = [line.get("lineNumber") for line in lines if _line_message_code(line) == "200"]
        return bool(found), f"expected at least one successful line; got {found or 'none'}"
    if op == "priced_line_with_positive_allowed_present":
        found = [
            str(line.get("lineNum"))
            for line in services
            if (amounts := _line_amount(line)) is not None and amounts[1] > 0
        ]
        return bool(found), f"expected a positive-allowed priced companion line; got {found or 'none'}"
    if op == "response_line_id_absent":
        found = [line.get("lineNumber") for line in lines if _line_id(line.get("lineNumber")) == _line_id(check["value"])]
        return not found, f"response must not contain synthetic line {check['value']}; got {found or 'none'}"
    if op == "response_line_id_present":
        found = [line.get("lineNumber") for line in lines if _line_id(line.get("lineNumber")) == _line_id(check["value"])]
        return bool(found), f"response must contain line {check['value']}; got {found or 'none'}"
    if op == "over_allowed_lines_return_code":
        output = _response_line_map(response)
        errors = []
        count = 0
        for line in services:
            amounts = _line_amount(line)
            if amounts is None or amounts[1] <= amounts[0]:
                continue
            count += 1
            identifier = _line_id(line.get("lineNum"))
            actual = output.get(identifier)
            code = _line_message_code(actual) if actual else "<missing>"
            if code != str(check["value"]):
                errors.append(f"line {identifier}: expected {check['value']}, got {code}")
        return count > 0 and not errors, "; ".join(errors) or f"{count} over-allowed line(s) returned {check['value']}"
    if op == "direct_amounts_reconcile":
        tolerance = _decimal(check.get("tolerance", "0.02")) or Decimal("0.02")
        output = _response_line_map(response)
        problems: list[str] = []
        expected_nc = Decimal("0")
        expected_excess = Decimal("0")
        count = 0
        for line in services:
            amounts = _line_amount(line)
            if amounts is None:
                problems.append(f"line {line.get('lineNum')}: missing chargeAmt/pdAllowed")
                continue
            count += 1
            billed, allowed = amounts
            nc = max(billed - min(billed, allowed), Decimal("0"))
            excess = max(allowed - billed, Decimal("0"))
            expected_nc += nc
            expected_excess += excess
            identifier = _line_id(line.get("lineNum"))
            actual_line = output.get(identifier)
            if actual_line is None:
                problems.append(f"line {identifier}: absent from response")
                continue
            actual_nc = _decimal(actual_line.get("totalNotCoveredAmount"))
            if actual_nc is None or abs(actual_nc - nc) > tolerance:
                problems.append(f"line {identifier} NC expected {_money(nc)}, got {actual_line.get('totalNotCoveredAmount')}")
            if _line_message_code(actual_line) != "200":
                problems.append(f"line {identifier} message expected 200, got {_line_message_code(actual_line)}")
        actual_claim_nc = _decimal(claim.get("claimLevelTotalNotCoveredAmount"))
        actual_excess = _decimal(claim.get("claimLevelExcessAmount"))
        if actual_claim_nc is None or abs(actual_claim_nc - expected_nc) > tolerance:
            problems.append(f"claim NC expected {_money(expected_nc)}, got {actual_claim_nc}")
        if actual_excess is None or abs(actual_excess - expected_excess) > tolerance:
            problems.append(f"claim excess expected {_money(expected_excess)}, got {actual_excess}")
        return count > 0 and not problems, "; ".join(problems) or (
            f"all {count} line NC values and claim NC/excess match request-derived values "
            f"(NC={_money(expected_nc)}, excess={_money(expected_excess)})"
        )
    if op == "grouped_amounts_reconcile":
        tolerance = _decimal(check.get("tolerance", "0.02")) or Decimal("0.02")
        included = [line for line in services if not _is_excluded(line)]
        excluded = [line for line in services if _is_excluded(line)]
        included_amounts = [(line, _line_amount(line)) for line in included]
        if not included or any(amount is None for _, amount in included_amounts):
            return False, "included grouped lines lack billed or allowed values"
        total_billed = sum((amount[0] for _, amount in included_amounts if amount), Decimal("0"))
        total_allowed = sum((amount[1] for _, amount in included_amounts if amount), Decimal("0"))
        output = _response_line_map(response)
        problems = []
        if total_billed <= 0:
            return False, f"included billed total must be positive; got {total_billed}"
        over_allowed = total_allowed > total_billed
        for line, amount in included_amounts:
            assert amount is not None
            billed, allowed = amount
            expected_nc = Decimal("0") if over_allowed else max(
                billed - billed * total_allowed / total_billed, Decimal("0")
            )
            identifier = _line_id(line.get("lineNum"))
            actual_line = output.get(identifier)
            actual_nc = _decimal(actual_line.get("totalNotCoveredAmount")) if actual_line else None
            if actual_line is None or actual_nc is None or abs(actual_nc - expected_nc) > tolerance:
                problems.append(
                    f"included line {identifier} NC expected {_money(expected_nc)}, got "
                    f"{actual_nc if actual_nc is not None else '<missing>'}"
                )
        for line in excluded:
            amount = _line_amount(line)
            if amount is None:
                problems.append(f"excluded line {line.get('lineNum')}: missing billed or allowed value")
                continue
            billed, allowed = amount
            expected_nc = max(billed - min(billed, allowed), Decimal("0"))
            identifier = _line_id(line.get("lineNum"))
            actual_line = output.get(identifier)
            actual_nc = _decimal(actual_line.get("totalNotCoveredAmount")) if actual_line else None
            if actual_line is None or actual_nc is None or abs(actual_nc - expected_nc) > tolerance:
                problems.append(
                    f"excluded line {identifier} NC expected {_money(expected_nc)}, got "
                    f"{actual_nc if actual_nc is not None else '<missing>'}"
                )
        return not problems, "; ".join(problems) or (
            f"all {len(included)} included and {len(excluded)} excluded lines reconcile; "
            f"included billed={_money(total_billed)}, allowed={_money(total_allowed)}"
        )
    if op == "rnc_present":
        expected = str(check["value"])
        actual = _json_values(response, "lineItems[*].orders[*].reasonNotCovered")
        found = [str(value) for value in actual]
        return expected in found, f"expected RNC {expected}; response RNC values {found or 'none'}"
    if op == "rnc_matches_request_ppo_disc_reason":
        expected = str(pricing.get("ppoDiscReason") or "")
        actual = [str(value) for value in _json_values(response, "lineItems[*].orders[*].reasonNotCovered")]
        return bool(expected) and expected in actual, f"expected fallback RNC {expected or '<missing>'}; response RNC values {actual or 'none'}"
    if op == "response_text_contains":
        actual = [str(value) for value in _json_values(response, check["path"])]
        expected = str(check["value"]).casefold()
        found = any(expected in value.casefold() for value in actual)
        return found, f"expected response text containing {check['value']!r}; got {actual or 'no text'}"
    if op == "claim_excess_positive":
        actual = _decimal(claim.get("claimLevelExcessAmount"))
        passed = actual is not None and actual > 0
        return passed, f"claimLevelExcessAmount expected > 0; got {actual if actual is not None else '<missing>'}"
    if op == "case_rate_amounts_reconcile":
        tolerance = _decimal(check.get("tolerance", "0.02")) or Decimal("0.02")
        allowed_total = _decimal(pricing.get("allowedCharges"))
        if allowed_total is None:
            return False, "request pricingDetails.allowedCharges is missing or invalid"
        included = [line for line in services if not _is_excluded(line)]
        excluded = [line for line in services if _is_excluded(line)]
        included_values: list[tuple[dict[str, Any], Decimal, Decimal]] = []
        for line in included:
            amounts = _line_amount(line)
            if amounts is None:
                return False, f"included line {line.get('lineNum')} lacks billed or allowed values"
            billed, _ = amounts
            limit = _decimal(line.get("planCoveredExpenseLimit"))
            if limit is None or _is_unlimited_limit(line.get("planCoveredExpenseLimit")):
                basis = billed
            else:
                basis = min(billed, limit)
            included_values.append((line, billed, basis))
        basis_total = sum((item[2] for item in included_values), Decimal("0"))
        if not included_values or basis_total <= 0:
            return False, "case-rate scenario requires positive included-line billed/plan-limit basis"
        group_covered = min(allowed_total, basis_total)
        output = _response_line_map(response)
        problems: list[str] = []
        expected_claim_nc = Decimal("0")
        for line, billed, basis in included_values:
            covered = group_covered * basis / basis_total
            expected_nc = max(billed - min(billed, covered), Decimal("0"))
            expected_claim_nc += expected_nc
            identifier = _line_id(line.get("lineNum"))
            actual_line = output.get(identifier)
            actual_nc = _decimal(actual_line.get("totalNotCoveredAmount")) if actual_line else None
            if actual_line is None or actual_nc is None or abs(actual_nc - expected_nc) > tolerance:
                problems.append(
                    f"included line {identifier} NC expected {_money(expected_nc)}, got "
                    f"{actual_nc if actual_nc is not None else '<missing>'}"
                )
        for line in excluded:
            amounts = _line_amount(line)
            if amounts is None:
                problems.append(f"excluded line {line.get('lineNum')} lacks billed or allowed values")
                continue
            billed, allowed = amounts
            expected_nc = max(billed - min(billed, allowed), Decimal("0"))
            expected_claim_nc += expected_nc
            identifier = _line_id(line.get("lineNum"))
            actual_line = output.get(identifier)
            actual_nc = _decimal(actual_line.get("totalNotCoveredAmount")) if actual_line else None
            if actual_line is None or actual_nc is None or abs(actual_nc - expected_nc) > tolerance:
                problems.append(
                    f"excluded line {identifier} NC expected {_money(expected_nc)}, got "
                    f"{actual_nc if actual_nc is not None else '<missing>'}"
                )
        actual_claim_nc = _decimal(claim.get("claimLevelTotalNotCoveredAmount"))
        if actual_claim_nc is None or abs(actual_claim_nc - expected_claim_nc) > tolerance:
            problems.append(f"claim NC expected {_money(expected_claim_nc)}, got {actual_claim_nc}")
        return not problems, "; ".join(problems) or (
            f"case-rate line and claim NC reconcile using the lesser of billed and finite plan limits "
            f"(covered basis={_money(basis_total)}, group allowed={_money(group_covered)}, "
            f"claim NC={_money(expected_claim_nc)})"
        )
    return False, f"unsupported check operation {op!r}"


def _response_blocker(result: dict[str, Any], response: dict[str, Any] | None, catalog: dict[str, Any]) -> str | None:
    request_response = result.get("response")
    request_response = request_response if isinstance(request_response, dict) else {}
    http_status = _decimal(request_response.get("status"))
    blockers = catalog.get("execution_blockers", {})
    if http_status is None:
        return "Bruno result has no usable HTTP response"
    if int(http_status) in blockers.get("http_statuses", []):
        return f"HTTP {int(http_status)} prevents business-result evaluation"
    if response is None:
        return "Bruno response body is not a JSON object"
    message = response.get("message")
    message = message if isinstance(message, dict) else {}
    code = str(message.get("code") or "")
    if code in {str(value) for value in blockers.get("response_message_codes", [])}:
        return f"execution dependency response {code}: {message.get('description', '')}".strip()
    text = " ".join(str(message.get(key) or "") for key in ("description", "details")).casefold()
    for phrase in blockers.get("response_message_text_contains", []):
        if str(phrase).casefold() in text:
            return f"execution dependency response: {message.get('description', phrase)}"
    return None


def _actual_summary(result: dict[str, Any] | None, blocker: str | None = None) -> str:
    if result is None:
        return "No Bruno result was found for this payload."
    if blocker:
        return f"Blocked: {blocker}"
    response = response_body(result) or {}
    response_meta = result.get("response")
    response_meta = response_meta if isinstance(response_meta, dict) else {}
    message = response.get("message")
    message = message if isinstance(message, dict) else {}
    claim = response.get("claimLevel")
    claim = claim if isinstance(claim, dict) else {}
    lines = []
    for line in _response_lines(response):
        orders = line.get("orders") or []
        rnc = sorted(
            {
                str(order.get("reasonNotCovered"))
                for order in orders
                if isinstance(order, dict) and str(order.get("reasonNotCovered")) not in {"", "0", "None"}
            }
        )
        lines.append(
            f"{line.get('lineNumber')} code={_line_message_code(line)} "
            f"NC={line.get('totalNotCoveredAmount')} RNC={rnc}"
        )
    return (
        f"HTTP {response_meta.get('status')}; claim code={message.get('code')}; "
        f"group={claim.get('claimLevelGroupMethod')}; "
        f"claim NC={claim.get('claimLevelTotalNotCoveredAmount')}; "
        f"excess={claim.get('claimLevelExcessAmount')}; lines=[{'; '.join(lines)}]"
    )


def _expanded_expected(scenario: dict[str, Any], request: dict[str, Any] | None) -> str:
    if request is None:
        return scenario["expected"]
    checked = {item.get("op") for item in scenario.get("checks", [])}
    if not checked.intersection({"direct_amounts_reconcile", "grouped_amounts_reconcile"}):
        return scenario["expected"]
    _, _, services = _request_parts(request)
    expected_lines: list[str] = []
    if "direct_amounts_reconcile" in checked:
        for line in services:
            amounts = _line_amount(line)
            if amounts is None:
                continue
            billed, allowed = amounts
            nc = max(billed - min(billed, allowed), Decimal("0"))
            excess = max(allowed - billed, Decimal("0"))
            expected_lines.append(
                f"{line.get('lineNum')}: NC {_money(nc):.2f}, excess {_money(excess):.2f}"
            )
    else:
        included = [line for line in services if not _is_excluded(line)]
        excluded = [line for line in services if _is_excluded(line)]
        all_amounts = [_line_amount(line) for line in included]
        if all(all_amounts) and included:
            total_billed = sum((item[0] for item in all_amounts if item), Decimal("0"))
            total_allowed = sum((item[1] for item in all_amounts if item), Decimal("0"))
            for line, item in zip(included, all_amounts, strict=True):
                assert item is not None
                billed, _ = item
                nc = Decimal("0") if total_allowed > total_billed else max(
                    billed - billed * total_allowed / total_billed, Decimal("0")
                )
                expected_lines.append(f"{line.get('lineNum')}: NC {_money(nc):.2f}")
        for line in excluded:
            amount = _line_amount(line)
            if amount is not None:
                billed, allowed = amount
                expected_lines.append(
                    f"{line.get('lineNum')}: NC {_money(max(billed - min(billed, allowed), Decimal('0'))):.2f}"
                )
    return scenario["expected"] + (f" Input-derived expected amounts: {'; '.join(expected_lines)}." if expected_lines else "")


@dataclass
class Outcome:
    scenario_id: str
    scenario_name: str
    category: str
    payload_name: str
    expected: str
    actual: str
    comments: str
    status: str
    executed_at: str
    design_refs: str


def evaluate(
    scenario: dict[str, Any],
    result: dict[str, Any] | None,
    catalog: dict[str, Any],
    executed_at: str,
) -> Outcome:
    payload_name = Path(result_filename(result).replace("\\", "/")).name if result else "(not run)"
    response = response_body(result) if result else None
    request = request_body(result) if result else None
    expected = _expanded_expected(scenario, request)
    refs = "; ".join(scenario.get("design_refs", []))
    if result is None:
        return Outcome(
            scenario["id"], scenario["name"], scenario["category"], payload_name,
            expected, "No matching payload result in this Bruno execution.", "", "Not Run",
            executed_at, refs,
        )
    blocker = _response_blocker(result, response, catalog)
    if blocker:
        return Outcome(
            scenario["id"], scenario["name"], scenario["category"], payload_name,
            expected, _actual_summary(result, blocker), "", "Blocked", executed_at, refs,
        )
    if request is None:
        return Outcome(
            scenario["id"], scenario["name"], scenario["category"], payload_name,
            expected, "Blocked: Bruno request body could not be read as JSON.", "", "Blocked",
            executed_at, refs,
        )
    readiness = scenario.get("readiness", "ready")
    activation = scenario.get("activation")
    if readiness == "conditional":
        activation_passed, activation_message = _comparison(activation, request, response)
        if not activation_passed:
            return Outcome(
                scenario["id"], scenario["name"], scenario["category"], payload_name,
                expected, f"Blocked: {scenario.get('conditional_reason', activation_message)}; "
                f"{_actual_summary(result)}", "", "Blocked", executed_at, refs,
            )
    if readiness == "design_pending":
        return Outcome(
            scenario["id"], scenario["name"], scenario["category"], payload_name,
            expected, f"Blocked: expected-result checks are not configured. {_actual_summary(result)}",
            "", "Blocked", executed_at, refs,
        )
    failures: list[str] = []
    for condition in scenario.get("conditions", []):
        passed, message = _precondition(condition, request, response)
        if not passed:
            failures.append(message)
    if failures:
        return Outcome(
            scenario["id"], scenario["name"], scenario["category"], payload_name,
            expected, f"Blocked: scenario input does not meet its preconditions ({'; '.join(failures)}); "
            f"{_actual_summary(result)}", "", "Blocked", executed_at, refs,
        )
    critical: list[str] = []
    partial: list[str] = []
    for check in scenario.get("checks", []):
        passed, message = _comparison(check, request, response or {})
        if not passed:
            (partial if check.get("severity") == "partial" else critical).append(message)
    if critical:
        status, comments = "Fail", "; ".join(critical + partial)
    elif partial:
        status, comments = "Partial Pass", "; ".join(partial)
    else:
        status, comments = "Pass", ""
    return Outcome(
        scenario["id"], scenario["name"], scenario["category"], payload_name,
        expected, _actual_summary(result), comments, status, executed_at, refs,
    )


def run_catalog(
    catalog: dict[str, Any], results: list[dict[str, Any]], executed_at: str
) -> tuple[list[Outcome], list[dict[str, Any]]]:
    used_results: set[int] = set()
    outcomes: list[Outcome] = []
    for scenario in catalog["scenarios"]:
        matches = [
            (index, result)
            for index, result in enumerate(results)
            if match_payload(result_filename(result), scenario)
        ]
        if not matches:
            outcomes.append(evaluate(scenario, None, catalog, executed_at))
            continue
        for index, result in matches:
            used_results.add(index)
            outcomes.append(evaluate(scenario, result, catalog, _execution_time(result, executed_at)))
    ignored_prefixes = ("00-auth/",)
    unmapped = []
    for index, result in enumerate(results):
        filename = result_filename(result)
        normalized = filename.replace("\\", "/").lower()
        if index in used_results or not filename or normalized.startswith(ignored_prefixes):
            continue
        unmapped.append(
            {
                "payload_name": Path(filename.replace("\\", "/")).name,
                "path": filename.replace("\\", "/"),
                "response_status": (result.get("response") or {}).get("status"),
                "note": "No scenario mapping in the October 16 active design catalog; keep out of pass/fail totals until it is adopted or given a new scenario ID.",
            }
        )
    return outcomes, unmapped


def _execution_time(result: dict[str, Any], fallback: str) -> str:
    for key in ("executedAt", "startedAt", "timestamp", "createdAt"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    response = result.get("response")
    headers = response.get("headers") if isinstance(response, dict) else None
    if isinstance(headers, dict):
        for key, value in headers.items():
            if key.casefold() == "date" and value:
                return str(value)
    elif isinstance(headers, list):
        for header in headers:
            if isinstance(header, dict) and str(header.get("name", "")).casefold() == "date":
                if header.get("value"):
                    return str(header["value"])
    return f"{fallback} (report generation time; execution time not recorded)"
