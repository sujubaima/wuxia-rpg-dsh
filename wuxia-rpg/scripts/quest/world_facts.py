#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""槽位级规范世界事实：定义、类型、互斥与受控写入。"""
import copy


VERSION = 1
FACT_STATUSES = {"unknown", "alleged", "verified", "refuted"}
VALUE_TYPES = {"bool", "enum", "number", "string", "entity", "set"}
REVISION_POLICIES = {"explicit", "free"}


def empty_world_facts():
    return {"version": VERSION, "definitions": {}, "records": {}}


def normalize_world_facts(data):
    if not isinstance(data, dict):
        return empty_world_facts()
    definitions = data.get("definitions")
    records = data.get("records")
    return {
        "version": VERSION,
        "definitions": copy.deepcopy(definitions) if isinstance(definitions, dict) else {},
        "records": copy.deepcopy(records) if isinstance(records, dict) else {},
    }


def _fact_parts(fact_key):
    if not isinstance(fact_key, str) or not fact_key.strip():
        raise ValueError("事实键必须为非空字符串")
    key = fact_key.strip()
    body, marker, scope = key.rpartition("@")
    subject, dot, predicate = body.partition(".")
    if not marker or not subject or not dot or not predicate or not scope:
        raise ValueError(f"事实键【{key}】须符合 <subject>.<predicate>@<scope>")
    return key, subject, predicate, scope


def _infer_value_type(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, (list, tuple, set)):
        return "set"
    return "string"


def normalize_definition(raw, fact_key=None, sample_value=None):
    raw = raw if isinstance(raw, dict) else {}
    key = fact_key or raw.get("fact_key") or raw.get("事实键") or raw.get("事实")
    if not key and raw.get("主体") and raw.get("谓词"):
        key = f"{raw['主体']}.{raw['谓词']}@{raw.get('范围') or 'world'}"
    key, subject, predicate, scope = _fact_parts(key)
    value_type = raw.get("value_type") or raw.get("值类型")
    allowed = raw.get("allowed_values")
    if allowed is None:
        allowed = raw.get("可选值")
    if value_type is None:
        value_type = "enum" if isinstance(allowed, list) else _infer_value_type(sample_value)
    if value_type not in VALUE_TYPES:
        raise ValueError(f"事实【{key}】值类型【{value_type}】不受支持")
    if value_type == "enum":
        if not isinstance(allowed, list) or not allowed:
            raise ValueError(f"枚举事实【{key}】须提供非空可选值")
        if len({repr(value) for value in allowed}) != len(allowed):
            raise ValueError(f"枚举事实【{key}】可选值重复")
    elif allowed is not None:
        raise ValueError(f"非枚举事实【{key}】不得提供可选值")
    revision_policy = raw.get("revision_policy") or raw.get("修订策略") or "explicit"
    if revision_policy not in REVISION_POLICIES:
        raise ValueError(f"事实【{key}】修订策略【{revision_policy}】不受支持")
    description = raw.get("description")
    if description is None:
        description = raw.get("描述")
    if description is not None and not isinstance(description, str):
        raise ValueError(f"事实【{key}】描述须为字符串")
    return {
        "fact_key": key,
        "subject": raw.get("subject") or raw.get("主体") or subject,
        "predicate": raw.get("predicate") or raw.get("谓词") or predicate,
        "scope": raw.get("scope") or raw.get("范围") or scope,
        "value_type": value_type,
        "allowed_values": copy.deepcopy(allowed) if allowed is not None else None,
        "exclusive_group": raw.get("exclusive_group") or raw.get("互斥组"),
        "revision_policy": revision_policy,
        "description": description.strip() if isinstance(description, str) else "",
    }


def _definition_signature(definition):
    return {
        key: definition.get(key)
        for key in ("subject", "predicate", "scope", "value_type", "allowed_values",
                    "exclusive_group", "revision_policy")
    }


def register_definition(store, raw, fact_key=None, sample_value=None):
    definition = normalize_definition(raw, fact_key, sample_value)
    key = definition["fact_key"]
    existing = store["definitions"].get(key)
    if existing is not None and _definition_signature(existing) != _definition_signature(definition):
        raise ValueError(f"事实定义【{key}】与已有定义不一致")
    if existing is None:
        store["definitions"][key] = definition
        return True
    existing_description = existing.get("description") or ""
    new_description = definition.get("description") or ""
    if existing_description and new_description and existing_description != new_description:
        raise ValueError(
            f"事实定义【{key}】描述与已有定义不一致；现有描述【{existing_description}】"
        )
    if not existing_description and new_description:
        existing["description"] = new_description
        return True
    return False


def register_definitions(store, definitions):
    changed = False
    for definition in definitions or []:
        changed = register_definition(store, definition) or changed
    return changed


def _validate_value(definition, value):
    value_type = definition["value_type"]
    valid = True
    if value_type == "bool":
        valid = isinstance(value, bool)
    elif value_type == "number":
        valid = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif value_type in ("string", "entity"):
        valid = isinstance(value, str) and bool(value.strip())
    elif value_type == "set":
        valid = isinstance(value, (list, tuple, set))
    elif value_type == "enum":
        valid = value in definition.get("allowed_values", [])
    if not valid:
        raise ValueError(f"事实【{definition['fact_key']}】取值不符合 {value_type} 定义")
    if value_type == "set":
        unique = {repr(item): item for item in value}
        return [unique[key] for key in sorted(unique)]
    return value


def _is_exclusive_active(value, status):
    return status == "verified" and value not in (False, None, "", 0, [], {})


def _check_exclusive_group(store, definition, value, status):
    group = definition.get("exclusive_group")
    if not group or not _is_exclusive_active(value, status):
        return
    for other_key, other_definition in store["definitions"].items():
        if other_key == definition["fact_key"] or other_definition.get("exclusive_group") != group:
            continue
        record = store["records"].get(other_key)
        if record and _is_exclusive_active(record.get("value"), record.get("status")):
            raise ValueError(
                f"事实【{definition['fact_key']}】与互斥组【{group}】中的【{other_key}】冲突"
            )


def _transition_allowed(existing, value, status, revision):
    if not existing:
        return True
    old_value = existing.get("value")
    old_status = existing.get("status", "unknown")
    if old_value == value and old_status == status:
        return True
    if revision:
        return True
    if old_status == "verified":
        return old_value == value and status == "verified"
    if old_status == "refuted" and old_value == value and status == "verified":
        return False
    if status == "unknown" and old_status != "unknown":
        return False
    return True


def upsert_fact(store, fact_key, value, status="verified", source="gm", evidence_ids=None,
                definition=None, revision=False, reason=None, updated_at=None):
    key, _, _, _ = _fact_parts(fact_key)
    if status not in FACT_STATUSES:
        raise ValueError(f"事实【{key}】状态【{status}】不合法")
    if key not in store["definitions"]:
        if definition is None:
            raise ValueError(f"事实【{key}】尚未注册定义")
        register_definition(store, definition, key, value)
    fact_definition = store["definitions"][key]
    value = _validate_value(fact_definition, value)
    before = copy.deepcopy(store["records"].get(key))
    allow_change = revision or fact_definition.get("revision_policy") == "free"
    if not _transition_allowed(before, value, status, allow_change):
        raise ValueError(
            f"事实【{key}】已有已确认/已证伪结论【{before.get('value')}】，须走显式事实修订"
        )
    if revision and (not isinstance(reason, str) or not reason.strip()):
        raise ValueError(f"修订事实【{key}】须提供非空 原因")
    if before and before.get("value") == value and before.get("status") == status:
        return False, before, before
    _check_exclusive_group(store, fact_definition, value, status)
    record = {
        "fact_id": key,
        "fact_key": key,
        "value": copy.deepcopy(value),
        "status": status,
        "source": source or "gm",
        "evidence_ids": list(evidence_ids or []),
        "updated_at": updated_at,
    }
    if revision:
        record["revision_reason"] = reason.strip()
    if before == record:
        return False, before, before
    store["records"][key] = record
    return True, before, copy.deepcopy(record)


def fact_record(store, fact_key):
    return store.get("records", {}).get(fact_key)


def fact_value(store, fact_key, default=None):
    record = fact_record(store, fact_key)
    if not record or record.get("status") != "verified":
        return default
    return record.get("value", default)
