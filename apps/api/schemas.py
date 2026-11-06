from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class AuthInput(Strict):
    username: str = Field(min_length=3, max_length=40, pattern=r'^[a-zA-Z0-9_\-\u4e00-\u9fff]+$')
    password: str = Field(min_length=8, max_length=128)


class Onboarding(Strict):
    budget: int = Field(default=25, ge=5, le=200)
    tags: list[str] = Field(default_factory=list, max_length=12)
    location: Literal['教学楼', '图书馆', '宿舍区'] = '教学楼'


class Proposal(Strict):
    key: Literal['budget_max', 'taste', 'goal', 'exclude_ingredient', 'exclude_category']
    value: str | int
    scope: Literal['persistent', 'temporary'] = 'persistent'
    quote: str = Field(min_length=1, max_length=1200)
    operation: Literal['upsert', 'delete'] = 'upsert'


class TurnPatch(Strict):
    budget_max: int | None = Field(default=None, ge=1, le=500)
    taste: Literal['清淡', '麻辣', '酸辣'] | None = None
    available_minutes: int | None = Field(default=None, ge=1, le=240)
    party_size: int | None = Field(default=None, ge=1, le=12)
    channel: Literal['all', 'canteen', 'delivery'] | None = None
    category: Literal['rice', 'noodle', 'salad', 'soup', 'bun', 'milk_tea'] | None = None
    exclude_ingredient: str | None = Field(default=None, max_length=30)
    exclude_category: str | None = Field(default=None, max_length=30)


class NarrativeProposal(Strict):
    title: str = Field(min_length=1, max_length=40)
    quote: str = Field(min_length=8, max_length=1200)
    scope: Literal['persistent', 'temporary', 'recent'] = 'recent'


class TurnPlan(Strict):
    intent: Literal['chat', 'answer', 'recommend', 'cheaper', 'faster', 'another', 'remember', 'clarify'] = 'chat'
    patch: TurnPatch = Field(default_factory=TurnPatch)
    proposals: list[Proposal] = Field(default_factory=list, max_length=5)
    narratives: list[NarrativeProposal] = Field(default_factory=list, max_length=2)
    clarification: str = Field(default='', max_length=160)


class NarrativeInput(Strict):
    title: str = Field(min_length=1, max_length=40)
    content: str = Field(min_length=8, max_length=2000)
    scope: Literal['persistent', 'temporary', 'recent'] = 'persistent'
    expected_version: int = Field(ge=0)

    @field_validator('title','content',mode='before')
    @classmethod
    def strip_text(cls,value):
        return value.strip() if isinstance(value,str) else value


class VersionInput(Strict):
    expected_version: int = Field(ge=0)


class ReplyDraft(Strict):
    text: str = Field(min_length=1, max_length=1600)


class ChatInput(Strict):
    conversation_id: str = Field(max_length=40)
    request_id: str = Field(min_length=8, max_length=80)
    expected_version: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=1200)


class ContextInput(Strict):
    weather: Literal['sunny', 'rainy'] = 'sunny'
    hour: int = Field(default=12, ge=0, le=23)
    location: Literal['教学楼', '图书馆', '宿舍区'] = '教学楼'
    available_minutes: int | None = Field(default=None, ge=10, le=180)


class MemoryInput(Strict):
    key: Literal['budget_max', 'taste', 'goal', 'exclude_ingredient', 'exclude_category']
    value: str | int
    scope: Literal['persistent', 'temporary'] = 'persistent'
    expected_version: int = Field(ge=0)


class SelectInput(Strict):
    food_id: str = Field(max_length=40)
    expected_version: int = Field(ge=0)


class FeedbackInput(Strict):
    eaten: bool = True
    actual_cents: int | None = Field(default=None, ge=0, le=100000)
    feedback: Literal['', '喜欢', '太辣了', '排队有点久', '分量刚好', '性价比高'] = ''
