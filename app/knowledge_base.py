

from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

RELEVANCE_THRESHOLD = 0.2

TOP_K = 3


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    content: str


DOCUMENTS: list[Document] = [
    Document(
        "refund_policy",
        "Refund Policy",
        "We offer full refunds within 14 days of purchase if you are not satisfied. "
        "Refunds are processed to the original payment method within 5-7 business days.",
    ),
    Document(
        "subscription_cancellation",
        "Cancelling a Subscription",
        "You can cancel your subscription anytime from Account > Billing > Cancel Subscription. "
        "Cancellation takes effect at the end of the current billing cycle; no partial refunds "
        "are issued for the remaining days.",
    ),
    Document(
        "password_reset",
        "Resetting Your Password",
        "To reset your password, click 'Forgot Password' on the login page and follow the "
        "emailed link. The link expires after 30 minutes.",
    ),
    Document(
        "data_export",
        "Exporting Your Data",
        "You can export all your account data in CSV or JSON format from Settings > Data Export. "
        "Exports are generated within 24 hours and emailed as a download link.",
    ),
    Document(
        "billing_cycle",
        "Billing Cycle",
        "Billing occurs monthly on the date you first subscribed. Annual plans are billed once "
        "per year with a 20% discount compared to monthly billing.",
    ),
    Document(
        "plan_upgrade_downgrade",
        "Upgrading or Downgrading Your Plan",
        "You can upgrade your plan instantly from Settings > Plan; the price difference is "
        "prorated. Downgrades take effect at the start of the next billing cycle.",
    ),
    Document(
        "uptime_sla",
        "Uptime SLA",
        "Our platform guarantees 99.9% uptime measured monthly. Service credits are issued "
        "automatically if uptime falls below this threshold.",
    ),
]

_corpus = [f"{d.title}. {d.content}" for d in DOCUMENTS]
_vectorizer = TfidfVectorizer(stop_words="english")
_doc_matrix = _vectorizer.fit_transform(_corpus)


def retrieve(query: str, top_k: int = TOP_K) -> list[tuple[Document, float]]:
    """Return the top_k documents for `query`, each with a cosine-similarity score."""
    query_vec = _vectorizer.transform([query])
    scores = cosine_similarity(query_vec, _doc_matrix)[0]
    ranked = sorted(zip(DOCUMENTS, scores), key=lambda pair: pair[1], reverse=True)
    return ranked[:top_k]
