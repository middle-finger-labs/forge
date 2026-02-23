"""LangGraph agent definitions and prompt templates for each pipeline stage."""

from agents.stage_1_business_analyst import (
    HUMAN_PROMPT_TEMPLATE as STAGE_1_HUMAN_TEMPLATE,
)
from agents.stage_1_business_analyst import (
    SYSTEM_PROMPT as STAGE_1_SYSTEM_PROMPT,
)
from agents.stage_2_researcher import (
    HUMAN_PROMPT_TEMPLATE as STAGE_2_HUMAN_TEMPLATE,
)
from agents.stage_2_researcher import (
    SYSTEM_PROMPT as STAGE_2_SYSTEM_PROMPT,
)
from agents.stage_3_architect import (
    HUMAN_PROMPT_TEMPLATE as STAGE_3_HUMAN_TEMPLATE,
)
from agents.stage_3_architect import (
    SYSTEM_PROMPT as STAGE_3_SYSTEM_PROMPT,
)
from agents.stage_4_pm import (
    HUMAN_PROMPT_TEMPLATE as STAGE_4_HUMAN_TEMPLATE,
)
from agents.stage_4_pm import (
    SYSTEM_PROMPT as STAGE_4_SYSTEM_PROMPT,
)
from agents.stage_5_engineer import (
    HUMAN_PROMPT_TEMPLATE as STAGE_5_HUMAN_TEMPLATE,
)
from agents.stage_5_engineer import (
    SYSTEM_PROMPT as STAGE_5_SYSTEM_PROMPT,
)
from agents.stage_6_qa import (
    HUMAN_PROMPT_TEMPLATE as STAGE_6_HUMAN_TEMPLATE,
)
from agents.stage_6_qa import (
    SYSTEM_PROMPT as STAGE_6_SYSTEM_PROMPT,
)
from agents.stage_7_cto import (
    HUMAN_PROMPT_TEMPLATE as STAGE_7_HUMAN_TEMPLATE,
)
from agents.stage_7_cto import (
    SYSTEM_PROMPT as STAGE_7_SYSTEM_PROMPT,
)

PROMPTS_BY_STAGE = {
    1: {"system": STAGE_1_SYSTEM_PROMPT, "human": STAGE_1_HUMAN_TEMPLATE},
    2: {"system": STAGE_2_SYSTEM_PROMPT, "human": STAGE_2_HUMAN_TEMPLATE},
    3: {"system": STAGE_3_SYSTEM_PROMPT, "human": STAGE_3_HUMAN_TEMPLATE},
    4: {"system": STAGE_4_SYSTEM_PROMPT, "human": STAGE_4_HUMAN_TEMPLATE},
    5: {"system": STAGE_5_SYSTEM_PROMPT, "human": STAGE_5_HUMAN_TEMPLATE},
    6: {"system": STAGE_6_SYSTEM_PROMPT, "human": STAGE_6_HUMAN_TEMPLATE},
    7: {"system": STAGE_7_SYSTEM_PROMPT, "human": STAGE_7_HUMAN_TEMPLATE},
}
