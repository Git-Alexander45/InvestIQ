"""All ORM models. Importing this package registers every table on ``Base.metadata``."""

from investiq.models.brokerage import BrokerageVerification
from investiq.models.market import (
    CorporateAction,
    DataQualityIssue,
    Dividend,
    EtfHolding,
    EtfHoldingsSnapshot,
    FundamentalsSnapshot,
    FxRate,
    Instrument,
    PriceBar,
    Quote,
)
from investiq.models.news import NewsAssessment, NewsCluster, NewsItem, NewsSource
from investiq.models.portfolio import (
    ExternalCost,
    OwnerHoldingEntry,
    PaperCashEntry,
    PaperDividend,
    PaperFill,
    PaperOrder,
    PaperPositionAdjustment,
    Portfolio,
    PortfolioMilestone,
    PortfolioSnapshot,
    TfsaProfile,
)
from investiq.models.research import (
    Analysis,
    BacktestRun,
    CycleStep,
    GradeChange,
    LeaderboardEntry,
    Prediction,
    PredictionEvaluation,
    Recommendation,
    ResearchCycle,
    Score,
    StrategyPromotion,
    StrategyVersion,
)
from investiq.models.system import (
    AiRequest,
    AuditLog,
    BackupRecord,
    BudgetLedger,
    EmailDelivery,
    JobRun,
    Notification,
    PreferenceVersion,
    Report,
)
from investiq.models.watchlist import Alert, PersonalNote, SavedInvestment, Watchlist

__all__ = [
    "AiRequest", "Alert", "Analysis", "AuditLog", "BacktestRun", "BackupRecord", "BrokerageVerification",
    "BudgetLedger", "CorporateAction", "CycleStep", "DataQualityIssue", "Dividend", "EmailDelivery",
    "EtfHolding", "EtfHoldingsSnapshot", "ExternalCost", "FundamentalsSnapshot", "FxRate", "GradeChange",
    "Instrument", "JobRun", "LeaderboardEntry", "NewsAssessment", "NewsCluster", "NewsItem", "NewsSource",
    "Notification", "OwnerHoldingEntry", "PaperCashEntry", "PaperDividend", "PaperFill", "PaperOrder",
    "PaperPositionAdjustment", "PersonalNote", "Portfolio", "PortfolioMilestone", "PortfolioSnapshot",
    "Prediction", "PredictionEvaluation", "PreferenceVersion", "PriceBar", "Quote", "Recommendation",
    "Report", "ResearchCycle", "SavedInvestment", "Score", "StrategyPromotion", "StrategyVersion",
    "TfsaProfile", "Watchlist",
]
