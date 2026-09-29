#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""槽位级规范世界事实：定义、类型、互斥与受控写入。"""
import copy
import re


VERSION = 1
FACT_STATUSES = {"unknown", "alleged", "verified", "refuted"}
VALUE_TYPES = {"bool", "enum", "number", "string", "entity", "set"}
REVISION_POLICIES = {"explicit", "free"}


_ABSTRACT_TOKENS = {
    "truth", "known", "unknown", "confirmed", "verified", "possible",
    "impossible", "enough", "sufficient", "progress", "stage", "state",
    "status", "value", "resolved", "solved", "complete", "ready", "clue",
    "evidence",
}

_ATTRIBUTE_TYPES = {"enum", "string", "entity"}
_BOOL = {"bool"}
_NUMBER = {"number"}

# 闭集目录：同名谓词只在列出的主体族和值类型上合法。
_PREDICATE_SPECS = {
    "party": {
        "stamina": _NUMBER,
    },
    "world": {
        "time": _NUMBER,
    },
    "player": {
        "location": {"string", "entity"},
        "region": {"string", "entity"},
    },
    "character": {
        "exists": _BOOL,
        "location": {"string", "entity"},
        "copper": _NUMBER,
        "hp": _NUMBER,
        "mp": _NUMBER,
        "relation": _NUMBER,
        "in_party": _BOOL,
        "dead": _BOOL,
        "contact": _BOOL,
        "identity": _ATTRIBUTE_TYPES,
        "origin": _ATTRIBUTE_TYPES,
        "affiliation": _ATTRIBUTE_TYPES,
        "role": _ATTRIBUTE_TYPES,
        "stance": _ATTRIBUTE_TYPES,
        "present": _BOOL,
        "alive": _BOOL,
        "captured": _BOOL,
        "escaped": _BOOL,
        "freed": _BOOL,
    },
    "item": {
        "exists": _BOOL,
        "location": {"string", "entity"},
        "owner": _ATTRIBUTE_TYPES,
        "source": _ATTRIBUTE_TYPES,
        "destination": _ATTRIBUTE_TYPES,
        "origin": _ATTRIBUTE_TYPES,
        "authenticity": {"enum", "string"},
        "integrity": {"enum", "string"},
        "quantity": _NUMBER,
        "available": _BOOL,
        "discovered": _BOOL,
        "obtained": _BOOL,
        "read": _BOOL,
        "examined": _BOOL,
        "delivered": _BOOL,
        "destroyed": _BOOL,
    },
    "document": {
        "exists": _BOOL,
        "location": {"string", "entity"},
        "owner": _ATTRIBUTE_TYPES,
        "source": _ATTRIBUTE_TYPES,
        "destination": _ATTRIBUTE_TYPES,
        "origin": _ATTRIBUTE_TYPES,
        "authenticity": {"enum", "string"},
        "available": _BOOL,
        "discovered": _BOOL,
        "obtained": _BOOL,
        "read": _BOOL,
        "examined": _BOOL,
        "delivered": _BOOL,
        "destroyed": _BOOL,
    },
    "information": {
        "source": _ATTRIBUTE_TYPES,
        "destination": _ATTRIBUTE_TYPES,
        "origin": _ATTRIBUTE_TYPES,
        "identity": _ATTRIBUTE_TYPES,
        "owner": _ATTRIBUTE_TYPES,
        "target": _ATTRIBUTE_TYPES,
        "terms": {"enum", "string", "set"},
        "authenticity": {"enum", "string"},
        "quantity": _NUMBER,
        "available": _BOOL,
        "linked": _BOOL,
        "discovered": _BOOL,
        "obtained": _BOOL,
        "read": _BOOL,
        "heard": _BOOL,
        "witnessed": _BOOL,
        "examined": _BOOL,
        "delivered": _BOOL,
        "destroyed": _BOOL,
    },
    "scene": {
        "exists": _BOOL,
        "location": {"string", "entity"},
        "presence": {"bool", "enum"},
        "discovered": _BOOL,
        "accessible": _BOOL,
        "visited": _BOOL,
        "examined": _BOOL,
        "opened": _BOOL,
        "closed": _BOOL,
        "guarded": _BOOL,
    },
    "faction": {
        "exists": _BOOL,
        "location": {"string", "entity"},
        "controller": _ATTRIBUTE_TYPES,
        "affiliation": _ATTRIBUTE_TYPES,
        "stance": _ATTRIBUTE_TYPES,
    },
    "choice": {
        "selected": _BOOL,
    },
    "quest": {
        "outcome": {"enum"},
    },
}

_ITEM_QUANTITY = re.compile(r"^item:([^.:@]+):quantity$")
_SKILL_VALUE = re.compile(r"^skill:([^.:@]+):(known|level)$")


def empty_world_facts():
    return {"version": VERSION, "definitions": {}, "records": {}}


def _subject_family(subject):
    return subject.split(":", 1)[0]


def _validate_subject(subject):
    family = _subject_family(subject)
    if family not in _PREDICATE_SPECS:
        raise ValueError(f"事实主体【{subject}】类型【{family}】不受支持")
    segments = subject.split(":")
    if family in {"party", "world", "player"}:
        if len(segments) != 1:
            raise ValueError(f"事实主体【{subject}】格式不合法")
    elif len(segments) < 2 or any(not segment.strip() for segment in segments[1:]):
        raise ValueError(f"事实主体【{subject}】须提供具体标识")
    if family == "choice" and len(segments) < 3:
        raise ValueError(f"选择事实主体【{subject}】须符合 choice:<quest-id>:<choice-id>")
    for token in re.split(r"[:_\-]+", ":".join(segments[1:]).lower()):
        if token in _ABSTRACT_TOKENS:
            raise ValueError(f"事实主体【{subject}】含抽象结论词【{token}】")
    return family


def _predicate_types(subject, predicate):
    family = _validate_subject(subject)
    if family == "character":
        item_match = _ITEM_QUANTITY.fullmatch(predicate)
        if item_match:
            return _NUMBER
        skill_match = _SKILL_VALUE.fullmatch(predicate)
        if skill_match:
            return _BOOL if skill_match.group(2) == "known" else _NUMBER
    if predicate in _ABSTRACT_TOKENS:
        raise ValueError(f"事实谓词【{predicate}】是抽象结论，不得作为事实条件")
    allowed = _PREDICATE_SPECS[family].get(predicate)
    if allowed is None:
        raise ValueError(f"事实主体类型【{family}】不支持谓词【{predicate}】")
    return allowed


def _fact_parts(fact_key):
    if not isinstance(fact_key, str) or not fact_key.strip():
        raise ValueError("事实键必须为非空字符串")
    key = fact_key.strip()
    body, marker, scope = key.rpartition("@")
    subject, dot, predicate = body.partition(".")
    if (not marker or not subject or not dot or not predicate or not scope
            or "." in predicate or "@" in subject or any(part != part.strip()
                                                            for part in (subject, predicate, scope))):
        raise ValueError(f"事实键【{key}】须符合 <subject>.<predicate>@<scope>")
    _predicate_types(subject, predicate)
    return key, subject, predicate, scope


def fact_key_parts(fact_key):
    """解析并校验事实键，供任务校验复用。"""
    return _fact_parts(fact_key)


def _infer_value_type(value):
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, (list, tuple, set)):
        return "set"
    return "string"


def _provided(raw, english, chinese):
    if english in raw:
        return raw[english]
    if chinese in raw:
        return raw[chinese]
    return None


def normalize_definition(raw, fact_key=None, sample_value=None):
    raw = raw if isinstance(raw, dict) else {}
    raw_key = _provided(raw, "fact_key", "事实键") or raw.get("事实")
    key = fact_key or raw_key
    if not key and raw.get("主体") and raw.get("谓词"):
        key = f"{raw['主体']}.{raw['谓词']}@{raw.get('范围') or 'world'}"
    key, subject, predicate, scope = _fact_parts(key)
    if raw_key is not None and str(raw_key).strip() != key:
        raise ValueError(f"事实定义键【{raw_key}】与注册键【{key}】不一致")
    for english, chinese, parsed in (
            ("subject", "主体", subject),
            ("predicate", "谓词", predicate),
            ("scope", "范围", scope)):
        explicit = _provided(raw, english, chinese)
        if explicit is not None and explicit != parsed:
            raise ValueError(f"事实【{key}】显式{chinese}【{explicit}】与事实键【{parsed}】不一致")
    value_type = raw.get("value_type") or raw.get("值类型")
    allowed = raw.get("allowed_values")
    if allowed is None:
        allowed = raw.get("可选值")
    if value_type is None:
        value_type = "enum" if isinstance(allowed, list) else _infer_value_type(sample_value)
    if value_type not in VALUE_TYPES:
        raise ValueError(f"事实【{key}】值类型【{value_type}】不受支持")
    permitted = _predicate_types(subject, predicate)
    if value_type not in permitted:
        raise ValueError(
            f"事实【{key}】谓词【{predicate}】不支持值类型【{value_type}】，"
            f"须为【{'/'.join(sorted(permitted))}】"
        )
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
        "subject": subject,
        "predicate": predicate,
        "scope": scope,
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
    if existing is not None:
        existing = normalize_definition(existing, key)
        store["definitions"][key] = existing
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


def validate_fact_value(definition, value):
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


def normalize_world_facts(data):
    if not isinstance(data, dict):
        return empty_world_facts()
    result = empty_world_facts()
    definitions = data.get("definitions")
    for key, raw in (definitions.items() if isinstance(definitions, dict) else ()):
        register_definition(result, raw, key)
    records = data.get("records")
    for key, raw in (records.items() if isinstance(records, dict) else ()):
        if key not in result["definitions"]:
            raise ValueError(f"事实记录【{key}】缺少定义")
        if not isinstance(raw, dict):
            raise ValueError(f"事实记录【{key}】须为对象")
        fact_key, _, _, _ = _fact_parts(key)
        status = raw.get("status", "unknown")
        if status not in FACT_STATUSES:
            raise ValueError(f"事实【{fact_key}】状态【{status}】不合法")
        value = validate_fact_value(result["definitions"][key], raw.get("value"))
        record = copy.deepcopy(raw)
        record.update({"fact_id": fact_key, "fact_key": fact_key,
                       "value": value, "status": status})
        result["records"][key] = record
    return result


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
    fact_definition = normalize_definition(store["definitions"][key], key)
    store["definitions"][key] = fact_definition
    value = validate_fact_value(fact_definition, value)
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
