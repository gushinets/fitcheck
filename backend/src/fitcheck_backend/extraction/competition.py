"""Fill missing structured evidence before saving manual website vacancies."""
from ..contracts.domain import Vacancy
from .fields import extract_competition


def with_competition(vacancy: Vacancy) -> Vacancy:
    extracted = extract_competition(vacancy.description)
    updates = {}
    provenance = dict(vacancy.provenance or {})
    if vacancy.proposal_count is None and 'proposalCount' in extracted:
        updates['proposal_count'] = extracted['proposalCount']
        provenance['proposalCount'] = 'text'
    if vacancy.average_bid is None and 'averageBid' in extracted:
        updates['average_bid'] = extracted['averageBid']
        # The value and its currency form one piece of evidence.
        updates['average_bid_currency'] = extracted.get('averageBidCurrency')
        provenance['averageBid'] = 'text'
        provenance.pop('averageBidCurrency', None)
        if updates['average_bid_currency'] is not None:
            provenance['averageBidCurrency'] = 'text'
    return vacancy.model_copy(update={**updates, 'provenance': provenance}) if updates else vacancy
