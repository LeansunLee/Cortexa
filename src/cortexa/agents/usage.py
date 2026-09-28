class UsageTotals:
    def __init__(self):
        self.calls = 0
        self.reported = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0

    def add(self, response):
        self.calls += 1
        usage = getattr(response, "usage_metadata", None)
        if not usage:
            raw = (getattr(response, "response_metadata", None) or {}).get("token_usage")
            if raw:
                usage = {"input_tokens": raw.get("prompt_tokens", 0), "output_tokens": raw.get("completion_tokens", 0), "total_tokens": raw.get("total_tokens")}
        if not usage:
            return
        self.reported += 1
        self.input_tokens += usage.get("input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)
        self.total_tokens += usage.get("total_tokens") or usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

    def stats(self):
        return {
            "token_count": self.total_tokens if self.reported else None,
            "input_tokens": self.input_tokens if self.reported else None,
            "output_tokens": self.output_tokens if self.reported else None,
            "usage_complete": self.calls == self.reported and self.calls > 0,
            "usage_source": "provider" if self.reported else "unavailable",
        }
