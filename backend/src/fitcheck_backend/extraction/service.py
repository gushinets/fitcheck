from uuid import uuid4

from pydantic import ValidationError

from ..auth.access import require_verified
from ..contracts.resources import ExtractionRequest, ExtractionResponse
from ..contracts.domain import Vacancy
from .content import extract_content
from .errors import ExtractionError
from .network import fetch_public_page


class ExtractionService:
    def __init__(self, limiter, *, fetch_page=fetch_public_page):
        self.limiter = limiter
        self.fetch_page = fetch_page

    def extract(self, principal, request: ExtractionRequest, client_ip: str) -> ExtractionResponse:
        require_verified(principal)
        self.limiter.enforce('extraction', {'user': str(principal.user_id), 'ip': client_ip})
        value = request.root
        if value.type == 'url':
            page = self.fetch_page(value.url)
            payload = extract_content(page.body, content_type=page.content_type, source_url=page.final_url)
        else:
            payload = extract_content(value.text, content_type='text/plain')
        if len(payload.get('title', '')) < 2 or len(payload.get('description', '')) < 30:
            raise ExtractionError('extraction_insufficient')
        try:
            vacancy = Vacancy.model_validate({'id': str(uuid4()), **payload})
        except ValidationError:
            raise ExtractionError('extraction_insufficient') from None
        # The caller reviews/edits this vacancy and explicitly saves a draft or
        # submits it for analysis. Extraction never overwrites an account draft.
        return ExtractionResponse(vacancy=vacancy)
