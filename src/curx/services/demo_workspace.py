from datetime import UTC, datetime
from uuid import UUID

from curx.domain.schemas import (
    AnswerEvent,
    AnswerEventType,
    AnswerResponse,
    Citation,
    KnowledgeSpace,
    SourceSummary,
    WorkspaceSnapshot,
)

PRODUCT_QA_ID = UUID("11111111-1111-4111-8111-111111111111")
FIRMWARE_ID = UUID("22222222-2222-4222-8222-222222222222")
MANUAL_ID = UUID("33333333-3333-4333-8333-333333333333")

SOURCE_PRODUCT_SPEC_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1")
SOURCE_BATTERY_GUIDE_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2")
SOURCE_FIRMWARE_SPEC_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3")


def get_workspace_snapshot() -> WorkspaceSnapshot:
    now = datetime.now(UTC)
    return WorkspaceSnapshot(
        current_user="张明",
        spaces=[
            KnowledgeSpace(
                id=PRODUCT_QA_ID,
                name="产品问答",
                description="产品常见问题与解答",
                document_count=128,
                health_percent=86,
                visibility="internal",
                color="blue",
                icon="cube",
            ),
            KnowledgeSpace(
                id=FIRMWARE_ID,
                name="固件助手",
                description="固件相关知识与说明",
                document_count=96,
                health_percent=82,
                visibility="internal",
                color="green",
                icon="chip",
            ),
            KnowledgeSpace(
                id=MANUAL_ID,
                name="操作手册",
                description="使用指南与操作说明",
                document_count=64,
                health_percent=79,
                visibility="internal",
                color="purple",
                icon="book",
            ),
        ],
        recent_questions=[
            "电池充电截止电压是多少？",
            "设备休眠功耗优化方案",
            "Bootloader 升级流程",
            "USB 通信异常处理方式",
            "温度保护阈值说明",
        ],
        saved_questions=[
            "如何判断电池是否需要校准？",
            "OTA 升级失败如何恢复？",
            "设备指示灯状态含义",
        ],
        sources=[
            SourceSummary(
                id=SOURCE_PRODUCT_SPEC_ID,
                title="产品规格书",
                version="v2.3.1",
                page=12,
                location="3.2 电池与充电规格",
                excerpt="充电截止电压（CV 目标电压）：4.20V（±0.05V）；充电电流（CC）：标准 1.0A。",
                relevance="高相关",
                source_type="pdf",
                updated_at=now,
            ),
            SourceSummary(
                id=SOURCE_BATTERY_GUIDE_ID,
                title="电池充电管理设计指南",
                version="v1.8.0",
                page=23,
                location="5.2 充电流程说明",
                excerpt=(
                    "当电池电压达到 CV 阶段目标电压 4.20V 时，进入恒压充电阶段，"
                    "直至充电电流降至 100mA 以下。"
                ),
                relevance="高相关",
                source_type="pdf",
                updated_at=now,
            ),
            SourceSummary(
                id=SOURCE_FIRMWARE_SPEC_ID,
                title="固件设计说明",
                version="v1.8.0",
                page=78,
                location="4.3 充电控制逻辑",
                excerpt=(
                    "充电截止电压可通过寄存器 0x2001_0034 的参数进行配置，"
                    "范围：4.10V ~ 4.25V。"
                ),
                relevance="中相关",
                source_type="pdf",
                updated_at=now,
            ),
        ],
    )


def answer_question(question: str) -> AnswerResponse:
    snapshot = get_workspace_snapshot()
    evidence_ids = [source.id for source in snapshot.sources]
    events = [
        AnswerEvent(
            type=AnswerEventType.started,
            label="理解问题",
            summary="识别到问题聚焦于电池充电截止电压。",
            duration_ms=120,
        ),
        AnswerEvent(
            type=AnswerEventType.query_understood,
            label="检索资料",
            summary="在产品问答知识空间内应用可见性过滤。",
            duration_ms=180,
        ),
        AnswerEvent(
            type=AnswerEventType.retrieval_started,
            label="提取证据",
            summary="混合检索命中产品规格、充电指南与固件说明。",
            duration_ms=420,
            safe_source_ids=evidence_ids,
        ),
        AnswerEvent(
            type=AnswerEventType.evidence_ready,
            label="生成回答",
            summary="选取 3 条可引用证据进入上下文包。",
            duration_ms=160,
            safe_source_ids=evidence_ids,
        ),
        AnswerEvent(
            type=AnswerEventType.completed,
            label="回答完成",
            summary="答案已生成并绑定固定来源分块。",
            duration_ms=820,
            safe_source_ids=evidence_ids,
        ),
    ]

    citations = [
        Citation(
            order=1,
            source_id=SOURCE_PRODUCT_SPEC_ID,
            title="产品规格书 v2.3.1",
            chunk_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1"),
            page=12,
            location="3.2 电池与充电规格",
            excerpt="充电截止电压（CV 目标电压）：4.20V（±0.05V）。",
            score=0.94,
        ),
        Citation(
            order=2,
            source_id=SOURCE_BATTERY_GUIDE_ID,
            title="电池充电管理设计指南 v1.8.0",
            chunk_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2"),
            page=23,
            location="5.2 充电流程说明",
            excerpt="达到 4.20V 后进入恒压充电阶段，直至电流降至阈值以下。",
            score=0.91,
        ),
        Citation(
            order=3,
            source_id=SOURCE_FIRMWARE_SPEC_ID,
            title="固件设计说明 v1.8.0",
            chunk_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3"),
            page=78,
            location="4.3 充电控制逻辑",
            excerpt="寄存器参数可配置截止电压，范围为 4.10V ~ 4.25V。",
            score=0.72,
        ),
    ]

    normalized_question = question.strip("？? ")
    answer = (
        f"关于“{normalized_question}”，当前证据显示：标准充电模式下，电池充电截止电压为 "
        "4.20V，允许精度为 ±0.05V。若启用寿命优化策略，可按指南将目标值下调到 "
        "4.15V；如果需要修改该参数，应通过固件配置项变更并完成充电与老化验证。"
    )
    return AnswerResponse(
        answer=answer,
        confidence="高",
        handoff_required=False,
        events=events,
        citations=citations,
        next_actions=["继续追问", "生成步骤", "提取关键参数", "导出参考资料"],
    )
