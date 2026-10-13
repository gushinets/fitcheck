from typing import Annotated, Literal
from pydantic import Field, RootModel
from fitcheck_backend.api.errors import ErrorBody
from fitcheck_backend.contracts.domain import DTO, Identifier, Skill
from fitcheck_backend.contracts.resources import AnalysisResource


class JobReference(DTO):
    job_id: Identifier


class JobAdmissionResource(JobReference):
    type: Literal['analysis', 'skill_suggestions']
    status: Literal['queued', 'running', 'succeeded', 'failed']


class AnalysisQueued(JobReference):
    type: Literal["analysis"]
    status: Literal["queued"]


class AnalysisRunning(JobReference):
    type: Literal["analysis"]
    status: Literal["running"]


class AnalysisSucceeded(JobReference):
    type: Literal["analysis"]
    status: Literal["succeeded"]
    analysis_id: Identifier
    result: AnalysisResource


class AnalysisFailed(JobReference):
    type: Literal["analysis"]
    status: Literal["failed"]
    error: ErrorBody


class SuggestionsQueued(JobReference):
    type: Literal["skill_suggestions"]
    status: Literal["queued"]


class SuggestionsRunning(JobReference):
    type: Literal["skill_suggestions"]
    status: Literal["running"]


class SuggestionsSucceeded(JobReference):
    type: Literal["skill_suggestions"]
    status: Literal["succeeded"]
    skills: Annotated[list[Skill], Field(max_length=10)]


class SuggestionsFailed(JobReference):
    type: Literal["skill_suggestions"]
    status: Literal["failed"]
    error: ErrorBody


AnalysisStates = Annotated[AnalysisQueued | AnalysisRunning | AnalysisSucceeded | AnalysisFailed, Field(discriminator="status")]
SuggestionStates = Annotated[SuggestionsQueued | SuggestionsRunning | SuggestionsSucceeded | SuggestionsFailed, Field(discriminator="status")]


class JobState(RootModel[AnalysisStates | SuggestionStates]):
    pass


class ImportReference(DTO):
    import_id: Identifier


class ImportQueued(ImportReference):
    status: Literal["queued"]


class ImportRunning(ImportReference):
    status: Literal["running"]


class ImportSucceeded(ImportReference):
    status: Literal["succeeded"]
    imported_count: Annotated[int, Field(strict=True, ge=0)]


class ImportFailed(ImportReference):
    status: Literal["failed"]
    error: ErrorBody


class ImportState(RootModel[Annotated[ImportQueued | ImportRunning | ImportSucceeded | ImportFailed, Field(discriminator="status")]]):
    pass
