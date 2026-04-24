from dataclasses import dataclass, field


@dataclass
class TokenCounter:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_calls: int = 0
    _pending_records: list = field(default_factory=list)

    def add(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_calls += 1
        self._pending_records.append(
            {"prompt": prompt, "completion": completion}
        )

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def pending_count(self) -> int:
        return len(self._pending_records)

    def flush(self) -> list[dict]:
        records = self._pending_records.copy()
        self._pending_records.clear()
        return records
