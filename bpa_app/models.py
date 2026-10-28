from typing import Literal

from pydantic import BaseModel, Field

FORMATS = ("In-Person", "Virtual", "Open")
PARTICIPATION = ("Individual", "Team")
EVENT_TYPES = ("Testing", "Judged")
DIVISIONS = ("MS", "HS", "College")


class RubricItem(BaseModel):
    section: str | None  # name of the scoring rubric/table, e.g. "Presentation Rubric"
    criterion: str
    max_points: float | None
    description: str | None  # what earns high marks, if stated


class SectionTotal(BaseModel):
    section: str  # must equal the `section` used on its RubricItems
    total_points: float  # total stated in the document for that rubric


class EventDetails(BaseModel):  # extracted by Gemini from the PDF
    summary: str  # 2–3 plain-language sentences for students
    team_size_min: int | None
    team_size_max: int | None
    time_limits: list[str]  # e.g. "Presentation: 7 minutes", "Test: 60 minutes"
    submission_requirements: list[str]  # what must be submitted / produced
    presubmit_items: list[str]
    deadlines: list[str]  # as written in the PDF
    what_to_bring: list[str]
    competencies: list[str]  # skills/topics assessed (key for testing events)
    rubric: list[RubricItem]
    rubric_total_points: float | None  # one total over all items, only if stated
    rubric_section_totals: list[SectionTotal] = Field(default_factory=list)
    judging_notes: list[str]  # penalties, disqualifications, tie-breakers
    eligibility_notes: list[str]
    keywords: list[str]  # 5–10 search terms


class Event(BaseModel):
    id: str
    title: str
    subject: str
    format: Literal["In-Person", "Virtual", "Open"]
    participation: Literal["Individual", "Team"]
    event_type: list[Literal["Testing", "Judged"]]
    divisions: list[Literal["MS", "HS", "College"]]
    certification: bool | None
    presubmit: bool | None
    regional_deadline: str | None
    nlc_deadline: str | None
    view_url: str | None
    download_url: str | None
    pdf_file: str | None  # local filename, if downloaded
    has_text: bool
    details: EventDetails | None


class SearchFilters(BaseModel):
    """Sidebar filters inferred from a natural-language query; None means unspecified."""

    formats: list[str] | None = None
    participation: list[str] | None = None
    event_types: list[str] | None = None
    divisions: list[str] | None = None
    subjects: list[str] | None = None
    certification_only: bool | None = None
    presubmit_only: bool | None = None


class SearchHit(BaseModel):
    id: str
    reason: str  # why the event matches the query


class SearchResult(BaseModel):
    filters: SearchFilters = Field(default_factory=SearchFilters)
    results: list[SearchHit]  # ranked best first, max 12
    interpretation: str  # e.g. "Showing virtual team events for middle school"


class CriterionScore(BaseModel):
    criterion: str  # copied from the rubric
    max_points: float | None  # None for pass/fail required elements
    estimated_points: float | None
    evidence: str  # what in the submission supports the score
    suggestions: str  # concrete ways to earn more points


class Evaluation(BaseModel):
    criteria: list[CriterionScore]  # only criteria assessable from a document
    missing_requirements: list[str]
    strengths: list[str]
    top_3_improvements: list[str]
    estimated_total: float
    max_total: float  # points available for the criteria above
    cannot_assess: list[str]  # e.g. live presentation delivery


QUIZ_CHOICES = 4


class QuizQuestion(BaseModel):
    question: str  # markdown; may contain a fenced code snippet
    choices: list[str]  # exactly QUIZ_CHOICES
    answer_index: int  # 0-based index into choices
    explanation: str
    competency: str  # the event competency the question tests


class Quiz(BaseModel):
    questions: list[QuizQuestion]
