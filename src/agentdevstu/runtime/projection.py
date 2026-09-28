"""Bounded, explicitly partial model views of complete private observations."""

import json


def _encode(value):
    return json.dumps(value, ensure_ascii=False, default=str)


def model_result_text(result, *, max_bytes: int = 6000) -> str:
    """Keep small results exact; select whole rows/sources from oversized results.

    The complete raw result stays in the Observation snapshot. This function
    only controls the ToolMessage supplied to the next model call.
    """
    original = result.text if isinstance(result.text, str) else str(result.text)
    original_bytes = len(original.encode("utf-8"))
    if original_bytes <= max_bytes:
        return original

    observation = result.observation
    view = {
        "observation_id": observation.action_id,
        "source_type": str(observation.source_type),
        "status": str(observation.status),
        "projection": "selected_complete_items",
        "original_bytes": original_bytes,
        "summary": observation.summary,
    }
    raw = result.archive
    if observation.source_type == "DATA" and isinstance(raw, dict) and isinstance(raw.get("data"), list):
        rows = raw["data"]
        view.update(
            row_count=raw.get("row_count", len(rows)),
            returned_rows=raw.get("returned_rows", len(rows)),
            source_truncated=raw.get("truncated", False),
            columns=list(rows[0]) if rows and isinstance(rows[0], dict) else [],
            sample_rows=[],
            omitted_rows=len(rows),
        )
        for key in ("facets", "applied_parameters", "notice"):
            if key in raw:
                view[key] = raw[key]
                if len(_encode(view).encode("utf-8")) > max_bytes:
                    view.pop(key)
                    view[key + "_omitted"] = True
        for row in rows:
            view["sample_rows"].append(row)
            view["omitted_rows"] -= 1
            if len(_encode(view).encode("utf-8")) > max_bytes:
                view["sample_rows"].pop()
                view["omitted_rows"] += 1
                break
    elif observation.source_type == "AGENT" and isinstance(raw, dict):
        answer = raw.get("result")
        if isinstance(answer, str):
            view["agent_result"] = answer
            if len(_encode(view).encode("utf-8")) > max_bytes:
                view.pop("agent_result")
                view["agent_result_omitted"] = True
        sources = raw.get("sources") if isinstance(raw.get("sources"), list) else []
        view.update(source_count=len(sources), selected_sources=[], omitted_sources=len(sources))
        for source in sources:
            if not isinstance(source, dict):
                continue
            reference = {
                key: value
                for key, value in source.items()
                if key in {"type", "id", "name", "title", "url", "document_id", "source_id"}
                and isinstance(value, (str, int))
            }
            view["selected_sources"].append(reference)
            view["omitted_sources"] -= 1
            if len(_encode(view).encode("utf-8")) > max_bytes:
                view["selected_sources"].pop()
                view["omitted_sources"] += 1
                break
    else:
        sources = observation.evidence if observation.source_type in {"KNOWLEDGE", "WEB"} else []
        view.update(source_count=len(sources), selected_sources=[], omitted_sources=len(sources))
        for source in sources:
            view["selected_sources"].append(source)
            view["omitted_sources"] -= 1
            if len(_encode(view).encode("utf-8")) > max_bytes:
                view["selected_sources"].pop()
                view["omitted_sources"] += 1
                continue

    encoded = _encode(view)
    if len(encoded.encode("utf-8")) <= max_bytes:
        return encoded
    # A single metadata value can itself be oversized. The fixed reference
    # still identifies the archived Observation without inventing content.
    return _encode(
        {
            "observation_id": observation.action_id,
            "source_type": str(observation.source_type),
            "status": str(observation.status),
            "projection": "metadata_only",
            "original_bytes": original_bytes,
        }
    )
