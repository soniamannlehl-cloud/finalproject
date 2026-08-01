"""
Company Validation Agent tests.

yfinance is mocked throughout: these assert our ranking, classification, and
evidence-construction logic, not Yahoo's data. Hitting the live API here
would make the suite slow, flaky, and dependent on a third party's uptime.
"""

from unittest.mock import patch

import pytest
from contracts import SourceType, ValidationStatus

from app.agents import company_validation
from app.tools.yfinance_tool import CompanyMatch


def match(ticker="NVDA", name="NVIDIA Corporation", exchange="NMS", score=100.0):
    return CompanyMatch(
        ticker=ticker, name=name, exchange=exchange, quote_type="EQUITY",
        sector="Technology", industry="Semiconductors", score=score,
    )


class TestResolvedMatches:
    @patch("app.agents.company_validation.search_companies")
    def test_resolves_and_builds_evidence(self, mock_search):
        mock_search.return_value = [match()]
        evidence, status = company_validation.validate_company("NVDA", "r1", "t1")

        assert status == ValidationStatus.RESOLVED
        assert evidence.content["top_match"]["ticker"] == "NVDA"
        assert evidence.agent_id == company_validation.AGENT_ID
        assert evidence.source_type == SourceType.MARKET_DATA
        assert evidence.retrieved_at.tzinfo is not None

    @patch("app.agents.company_validation.search_companies")
    def test_exact_ticker_scores_higher_confidence_than_name(self, mock_search):
        """An exact ticker is unambiguous; a name match may not be."""
        mock_search.return_value = [match()]

        exact, _ = company_validation.validate_company("NVDA", "r1", "t1")
        by_name, _ = company_validation.validate_company("Nvidia", "r1", "t2")

        assert exact.content["exact_ticker_match"] is True
        assert by_name.content["exact_ticker_match"] is False
        assert exact.confidence > by_name.confidence

    @patch("app.agents.company_validation.search_companies")
    def test_ticker_match_is_case_insensitive(self, mock_search):
        mock_search.return_value = [match()]
        evidence, _ = company_validation.validate_company("nvda", "r1", "t1")
        assert evidence.content["exact_ticker_match"] is True

    @patch("app.agents.company_validation.search_companies")
    def test_offers_at_most_five_candidates(self, mock_search):
        """The confirmation UI needs a short list, not every global cross-listing."""
        mock_search.return_value = [match(ticker=f"T{i}", score=100 - i) for i in range(10)]
        evidence, _ = company_validation.validate_company("Delta", "r1", "t1")
        assert len(evidence.content["candidates"]) == 5


class TestNoMatch:
    @patch("app.agents.company_validation.get_settings")
    @patch("app.agents.company_validation.search_companies")
    def test_without_llm_key_defaults_to_not_found(self, mock_search, mock_settings):
        """
        Degrading to NOT_FOUND is the safe default: telling a user to try a
        ticker is actionable, whereas wrongly asserting a company is private
        is a confident falsehood.
        """
        mock_search.return_value = []
        mock_settings.return_value.openai_api_key = ""

        evidence, status = company_validation.validate_company("asdkjfh", "r1", "t1")
        assert status == ValidationStatus.NOT_FOUND
        assert evidence.content["candidates"] == []

    @patch("app.agents.company_validation._classify_no_match")
    @patch("app.agents.company_validation.search_companies")
    def test_private_company_classification_is_surfaced(self, mock_search, mock_classify):
        mock_search.return_value = []
        mock_classify.return_value = (ValidationStatus.PRIVATE_COMPANY, "privately held", None)

        evidence, status = company_validation.validate_company("SpaceX", "r1", "t1")
        assert status == ValidationStatus.PRIVATE_COMPANY
        assert "privately held" in evidence.content["message"]


class TestTypoDetection:
    @patch("app.agents.company_validation._llm_suggest_company")
    @patch("app.agents.company_validation._verify_suggestion")
    @patch("app.agents.company_validation.search_companies")
    def test_typo_suggests_correction(self, mock_search, mock_verify, mock_llm):
        """A misspelling like 'micrft' should not auto-confirm the wrong company."""
        wrong = match(ticker="MICR", name="Micron Solutions Inc", score=50.0)
        mock_search.return_value = [wrong]
        mock_llm.return_value = {"ticker": "MSFT", "name": "Microsoft Corporation"}
        mock_verify.return_value = match(ticker="MSFT", name="Microsoft Corporation", score=100.0)

        evidence, status = company_validation.validate_company("micrft", "r1", "t1")

        assert status == ValidationStatus.NOT_FOUND
        assert "Did you mean" in evidence.content["message"]
        assert evidence.content["suggested_match"]["ticker"] == "MSFT"
        assert "Microsoft" in evidence.content["message"]

    @patch("app.agents.company_validation._classify_no_match")
    @patch("app.agents.company_validation.search_companies")
    def test_no_search_results_surfaces_suggestion(self, mock_search, mock_classify):
        mock_search.return_value = []
        mock_classify.return_value = (
            ValidationStatus.NOT_FOUND,
            'We couldn\'t find a company matching "micrft". Did you mean Microsoft Corporation (MSFT)?',
            {"ticker": "MSFT", "name": "Microsoft Corporation"},
        )

        evidence, status = company_validation.validate_company("micrft", "r1", "t1")

        assert status == ValidationStatus.NOT_FOUND
        assert evidence.content["suggested_match"]["ticker"] == "MSFT"


class TestA2AHandler:
    @patch("app.agents.company_validation.search_companies")
    def test_conforms_to_the_shared_handler_contract(self, mock_search):
        """
        All capability handlers return the same 4-tuple so the A2A server can
        dispatch them uniformly: (evidence, confidence, degraded, claims).
        """
        mock_search.return_value = [match()]
        evidence, confidence, degraded, claims = company_validation.handle(
            {"query": "NVDA"}, "r1", "t1"
        )

        assert len(evidence) == 1
        assert 0.0 <= confidence <= 1.0
        assert degraded is None
        assert claims == []

    @pytest.mark.parametrize("inputs", [{}, {"query": ""}, None])
    def test_missing_query_raises_for_the_a2a_layer_to_convert(self, inputs):
        """
        Raises rather than returning empty: the A2A server turns this into a
        FAILED result, which is distinguishable from "searched and found
        nothing". Conflating the two would corrupt the evidence record.
        """
        with pytest.raises(ValueError, match="query"):
            company_validation.handle(inputs, "r1", "t1")


class TestExchangeRanking:
    """
    Ranking lives in the tool, but it materially affects validation: without
    it, "Tesla" can resolve to a Frankfurt cross-listing.
    """

    @patch("app.tools.yfinance_tool._raw_search")
    def test_us_primary_listing_outranks_cross_listing(self, mock_raw):
        from app.tools.yfinance_tool import search_companies

        mock_raw.return_value = [
            {"symbol": "TL0.F", "shortname": "Tesla Frankfurt", "quoteType": "EQUITY",
             "exchange": "FRA", "score": 20000},
            {"symbol": "TSLA", "shortname": "Tesla, Inc.", "quoteType": "EQUITY",
             "exchange": "NMS", "score": 15000},
        ]
        assert search_companies("Tesla")[0].ticker == "TSLA"

    @patch("app.tools.yfinance_tool._raw_search")
    def test_non_equity_instruments_are_excluded(self, mock_raw):
        """ETFs and indices are not companies to research."""
        from app.tools.yfinance_tool import search_companies

        mock_raw.return_value = [
            {"symbol": "SPY", "shortname": "SPDR S&P 500 ETF", "quoteType": "ETF",
             "exchange": "PCX", "score": 99999},
            {"symbol": "NVDA", "shortname": "NVIDIA", "quoteType": "EQUITY",
             "exchange": "NMS", "score": 100},
        ]
        results = search_companies("S&P")
        assert [r.ticker for r in results] == ["NVDA"]
