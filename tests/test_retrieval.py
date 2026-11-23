import pytest

from app.retrieval import Retriever, tokenize


@pytest.fixture(scope="module")
def retriever(tmp_path_factory) -> Retriever:
    from app.config import Settings

    return Retriever.from_dir(Settings(_env_file=None).docs_dir)


@pytest.mark.parametrize(
    "question, expected_title",
    [
        ("How long does standard shipping take?", "Delivery times"),
        ("Is shipping free?", "Shipping costs"),
        ("Can I return a gift card?", "Return window"),
        ("When will I get my refund?", "Refund timing"),
        ("My item arrived damaged", "Damaged or wrong items"),
        ("Do you accept bank transfers?", "Payment methods"),
        ("What happens if my payment fails?", "Failed payments"),
        ("Can I get an invoice for my company?", "Invoices"),
    ],
)
def test_top_hit_is_the_right_section(retriever, question, expected_title):
    hits = retriever.search(question, k=3)
    assert hits, question
    assert hits[0].chunk.title == expected_title
    assert hits[0].coverage >= 0.5


@pytest.mark.parametrize(
    "question", ["What is your CEO's name?", "Do you ship to Australia?", "Do you sell laptops?"]
)
def test_off_topic_questions_have_low_coverage(retriever, question):
    assert all(h.coverage < 0.5 for h in retriever.search(question, k=3))


def test_tokenize_matches_word_forms():
    assert tokenize("takes") == tokenize("take")
    assert tokenize("arrived") == tokenize("arrives")
    assert tokenize("refunds") == tokenize("refund")
    assert tokenize("How do I") == []
