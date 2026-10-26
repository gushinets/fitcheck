"""Stable, safe errors shared by extraction policy and the HTTP boundary."""

_ERRORS = {
    "invalid_url": (400, "Enter a valid HTTP or HTTPS URL, or use manual input."),
    "blocked_address": (403, "This address cannot be fetched. Please use manual input."),
    "redirect_limit": (502, "The page redirected too many times. Please use manual input."),
    "unsupported_content": (415, "This page is not supported. Please use manual input."),
    "response_too_large": (413, "The page is too large. Please use manual input."),
    "timeout": (504, "The page took too long to load. Retry or use manual input."),
    "fetch_failed": (502, "The page could not be loaded. Retry or use manual input."),
    "extraction_insufficient": (400, "There is not enough vacancy text. Please use manual input."),
}


class ExtractionError(Exception):
    def __init__(self, code: str):
        self.code = code
        self.status, self.message = _ERRORS[code]
        super().__init__(self.message)
