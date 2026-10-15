"""Offline regression checks for guarded 928-pool explorer UI.

The optional Node.js syntax check is skipped if Node is not installed; these
tests never use RPC, connect wallets, or modify saved research data.
"""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "research" / "index.html"
JS = ROOT / "research" / "research.js"
CSS = ROOT / "research" / "research.css"


class TestResearchExplorerUI(unittest.TestCase):
    def setUp(self):
        self.page = HTML.read_text(encoding="utf-8")
        self.javascript = JS.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")

    def test_evidence_filters_and_explicit_non_investment_caveat(self):
        for term in ('id="evidence"', 'value="regular"', 'value="context"',
                     'UI-only heuristic', 'not a safety, liquidity, or earning guarantee'):
            self.assertIn(term, self.page)
        self.assertIn('MIN_RESEARCH_WEEKLY_USD = 10', self.javascript)
        self.assertIn('MIN_OLD_SNAPSHOT_VOTES = 100', self.javascript)
        self.assertIn('p.observed_any_reward_positive_weeks !== 4', self.javascript)

    def test_no_cross_epoch_comparison_and_bad_denominators_are_deprioritized(self):
        self.assertIn('id="compare-panel"', self.page)
        self.assertIn('id="compare-items"', self.page)
        self.assertIn('id="clear-compare"', self.page)
        self.assertIn("selected.some(t => t.collection_epoch_utc !== p.collection_epoch_utc)",
                      self.javascript)
        self.assertIn('Cross-epoch comparison is disabled', self.javascript)
        self.assertIn('if (selected.length >= 3)', self.javascript)
        self.assertIn('if (direction === "ratio")', self.javascript)
        self.assertIn('sizeCautions(a).length > 0', self.javascript)
        self.assertIn('⚠ Fragile ratio', self.javascript)

    def test_research_priority_scoring_and_epoch_guard(self):
        for term in ('id="leaders-panel"', 'id="leaders-items"',
                     'value="score"', 'Incomplete USD data is unrated',
                     'No cross-epoch ranking'):
            self.assertIn(term, self.page)
        for term in ('function researchScore(p)', 'Math.min(39, Math.round(raw * evidenceFactor))',
                     'researchScore(p) === null', 'p.collection_epoch_utc === epoch',
                     'drawLeaders()', 'direction === "score"'):
            self.assertIn(term, self.javascript)

    def test_fragile_ratios_not_advertised_as_large_dollar_returns(self):
        self.assertIn('fragileRatio && p.illustrative_usd_per_million_inventory_votes', self.javascript)
        self.assertIn('"Unreliable"', self.javascript)
        self.assertIn('if (qa && qb) return a.index - b.index;', self.javascript)
        self.assertIn('const evidenceFactor = 0.25 + 0.75', self.javascript)
        self.assertIn('Math.min(39, Math.round(raw * evidenceFactor))', self.javascript)
        self.assertIn('Unreliable in the table', self.page)
        self.assertIn('graded evidence discounts', self.page)

    def test_saved_weekly_breakdown_is_read_only_and_explicitly_qualified(self):
        self.assertIn('function renderWeeklyBreakdown(p, root)', self.javascript)
        self.assertIn('fetch("/api/weekly?index="', self.javascript)
        self.assertIn('doc.detailRequest = p.index', self.javascript)
        self.assertIn('renderWeeklyBreakdown(p, root);', self.javascript)
        self.assertIn('Unknown quotes are never treated as $0', self.javascript)
        self.assertIn('data.weeks.length !== 4', self.javascript)
        self.assertIn('Pool trading pairs are read separately', self.page)
        self.assertIn('.weekly-analysis', self.css)
        self.assertIn('.fee-bar', self.css)
        self.assertIn('.bribe-bar', self.css)

    def test_p4_votes_are_separate_from_weekly_rewards_and_scoring(self):
        self.assertIn('function renderRollingVotes(p, root)', self.javascript)
        self.assertIn('fetch("/api/votes?index="', self.javascript)
        self.assertIn('renderRollingVotes(p, root);', self.javascript)
        self.assertIn('v.synchronized_with_reward_epochs !== false', self.javascript)
        self.assertIn('Vote share is measured against Voter totalWeight', self.javascript)
        self.assertIn('Not live voting power, future APR or a veNFT income estimate', self.javascript)
        self.assertIn('32 distinct Base blocks', self.page)
        self.assertIn('not</strong> synchronized', self.page)
        self.assertIn('.vote-analysis', self.css)

    def test_p5_four_week_analysis_is_descriptive_and_guarded(self):
        for term in (
            'function renderTrendSummary(data, parent)',
            'renderTrendSummary(data, content);',
            't.status !== "available"',
            'Latest vs previous completed week',
            'Four-week FEES · saved-price USD',
            'Four-week BRIBES · saved-price USD',
            't.latest_change_state === "new_positive_from_zero"',
            'percentage undefined',
            'not a trend forecast',
        ):
            self.assertIn(term, self.javascript)
        self.assertIn('P5 adds descriptive four-week reward breakdowns', self.page)
        self.assertIn('.trend-mix-track', self.css)
        # Research score and vote provenance calculations remain untouched.
        self.assertIn('function researchScore(p)', self.javascript)
        self.assertIn('function renderRollingVotes(p, root)', self.javascript)

    def test_p5_same_epoch_comparison_shows_reward_mix_without_vote_yield(self):
        for snippet in (
            'function renderComparisonRewardMix(p, card)',
            'renderComparisonRewardMix(p, card);',
            'fetch("/api/weekly?index="',
            'data.collection_epoch_utc !== p.collection_epoch_utc',
            'p.usd_coverage_complete',
            'new_positive_from_zero',
            'Saved four-week comparison unavailable',
            'P4 voting weights are NOT synchronized',
            'No positive priced rewards; split undefined',
            'Historical rewards priced at each batch',
        ):
            self.assertIn(snippet, self.javascript)
        self.assertIn('selected.some(t => t.collection_epoch_utc !== p.collection_epoch_utc)', self.javascript)
        self.assertIn('Compare up to three pools from the SAME saved collection epoch', self.page)
        self.assertIn('Saved USD quote times can differ by collection batch', self.page)
        self.assertIn('.compare-reward-mix', self.css)
        self.assertIn('.compare-reward-metrics', self.css)
        self.assertNotIn('innerHTML', self.javascript)
        self.assertNotIn('eval(', self.javascript)

    def test_p51_evidence_is_rendered_in_detail_and_comparison_without_scores(self):
        for term in (
            'function renderEvidenceNotes(trend, parent)',
            'P5.1 · Evidence & interpretation',
            'renderEvidenceNotes(t, section);',
            'renderEvidenceNotes(t, panel);',
            'Array.isArray(trend.evidence)',
            'new Set(["caution", "context", "unknown"])',
            'item.append(make("p", "mini", note.text))',
            'Evidence explanations unavailable',
            'Not predictions, probability',
        ):
            self.assertIn(term, self.javascript)
        self.assertIn("P5.1 displays saved four-week evidence notes", self.page)
        self.assertIn("P5.1 adds explainable retrospective flags", self.page)
        for term in ('.evidence-notes', '.evidence-item.evidence-caution',
                     '.evidence-item.evidence-unknown'):
            self.assertIn(term, self.css)
        self.assertNotIn('innerHTML', self.javascript)
        self.assertNotIn('eval(', self.javascript)

    def test_p61_beginner_researcher_views_keep_saved_data_and_evidence_visible(self):
        for term in (
            'data-view="beginner"',
            'id="view-beginner"',
            'id="view-researcher"',
            'aria-pressed="true"',
            'id="try-example"',
            'class="beginner-guide"',
            'class="provenance-strip"',
            'P2 · Historical rewards',
            'P4 · Observed votes',
            'USD · Saved batch quotes',
            'id="pool-table"',
            'class="research-only">Evidence / size filter',
            'class="research-only">Sort within selected epoch',
        ):
            self.assertIn(term, self.page)
        for term in (
            'function setView(mode)',
            'document.querySelector(".wrap").dataset.view = mode',
            '$(id).setAttribute("aria-pressed", String(active))',
            '$("status").value = "all"',
            '$("evidence").value = "all"',
            '$("sort").value = "index"',
            '$("view-beginner").addEventListener("click"',
            '$("view-researcher").addEventListener("click"',
            '$("try-example").addEventListener("click"',
            'showDetails(example)',
            'p.index === 1930 && p.collection_epoch_utc === EPOCH15',
        ):
            self.assertIn(term, self.javascript)
        for term in (
            '.wrap[data-view="beginner"] .research-only',
            '.wrap[data-view="researcher"] .beginner-guide',
            '.provenance-strip',
            '.mode-button.active',
            '@media(max-width:700px)',
        ):
            self.assertIn(term, self.css)
        self.assertIn('selected.some(t => t.collection_epoch_utc !== p.collection_epoch_utc)',
                      self.javascript)
        self.assertIn('Unknown value ≠ $0', self.page)
        self.assertNotIn('innerHTML', self.javascript)
        self.assertNotIn('localStorage', self.javascript)

    def test_p62_mobile_beginner_has_quick_search_cards_and_accessible_provenance(self):
        # Narrow-screen behavior stays a presentation-only transform.
        for term in (
            'class="beginner-data-notes"',
            'class="beginner-glossary"',
            'class="beginner-explanation"',
            'id="jump-to-search"',
            'class="beginner-directory-intro"',
            'class="directory-tech-note"',
            '<option value="10" selected>',
            'How should I read these historical numbers?',
            'BRIBES:</strong>',
            'veAERO:</strong>',
            'Epoch:</strong>',
        ):
            self.assertIn(term, self.page)
        for term in (
            '$("jump-to-search").addEventListener("click"',
            'field.scrollIntoView({behavior: "smooth", block: "center"})',
            'td.dataset.label = mobileLabels[i]',
            '"Mean USD / week", "Research score"',
            '"USD / 1M old votes", "Explore / compare"',
        ):
            self.assertIn(term, self.javascript)
        for term in (
            '.wrap[data-view="beginner"] .notice{display:none}',
            '.wrap[data-view="beginner"] .directory-tech-note{display:none}',
            '.wrap[data-view="researcher"] .beginner-data-notes',
            '.table-wrap tbody tr{display:grid',
            '.table-wrap td::before{content:attr(data-label)',
            '.table-wrap .compare-actions button{min-height:44px',
            '.wrap[data-view="beginner"] .provenance-strip{display:none}',
            '.beginner-actions button{min-height:44px}',
            '@media(max-width:700px)',
        ):
            self.assertIn(term, self.css)
        self.assertIn('selected.some(t => t.collection_epoch_utc !== p.collection_epoch_utc)',
                      self.javascript)
        self.assertNotIn('innerHTML', self.javascript)
        self.assertNotIn('localStorage', self.javascript)

    def test_p63_mobile_researcher_retains_provenance_with_compact_disclosure(self):
        for term in (
            'id="researcher-jump"',
            'class="researcher-mobile-summary researcher-only"',
            'class="researcher-alert"',
            'class="researcher-mobile-provenance"',
            'class="researcher-mobile-directory researcher-only"',
            'class="researcher-methodology research-only"',
            'class="researcher-methodology">',
            'Full screening and old-vote-ratio methodology',
            'How the 0–100 historical research score works',
            '32 pinned Base blocks',
            'Missing USD stays',
            'Reward weeks',
        ):
            self.assertIn(term, self.page)
        self.assertIn('Voting weights are not synchronized to the rewards', self.page)
        self.assertIn('Scores do not predict APR', self.page)
        for term in (
            '$("researcher-jump").addEventListener("click"',
            'field.scrollIntoView({behavior: "smooth", block: "center"})',
            'field.focus({preventScroll: true})',
        ):
            self.assertIn(term, self.javascript)
        for term in (
            '.wrap[data-view="beginner"] .researcher-only{display:none!important}',
            '.researcher-mobile-summary,.researcher-mobile-directory,#researcher-jump{display:none}',
            '.wrap[data-view="researcher"] .notice,',
            '.wrap[data-view="researcher"] .provenance-strip,',
            '.wrap[data-view="researcher"] .directory-tech-note{display:none}',
            '.wrap[data-view="researcher"] .researcher-mobile-summary{display:block',
            '.wrap[data-view="researcher"] .researcher-mobile-directory{display:block}',
            '.wrap[data-view="researcher"] #researcher-jump{display:block',
            'min-height:44px',
            '@media(max-width:700px)',
        ):
            self.assertIn(term, self.css)
        self.assertIn('selected.some(t => t.collection_epoch_utc !== p.collection_epoch_utc)',
                      self.javascript)
        self.assertNotIn('innerHTML', self.javascript)
        self.assertNotIn('localStorage', self.javascript)

    def test_no_unsafe_browser_or_network_features(self):
        self.assertIn('fetch("/api/research"', self.javascript)
        self.assertNotIn('innerHTML', self.javascript)
        self.assertNotIn('eval(', self.javascript)
        self.assertNotIn('localStorage', self.javascript)
        self.assertNotIn('wallet', self.javascript.lower().split('fetch("/api/research"')[0])
        self.assertIn('class="compare-items"', self.page)
        self.assertIn('.compare-card', self.css)

    @unittest.skipUnless(shutil.which("node"), "Node.js unavailable: skip JS syntax check")
    def test_javascript_syntax(self):
        result = subprocess.run(
            [shutil.which("node"), "--check", str(JS)],
            text=True, capture_output=True, check=False, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
