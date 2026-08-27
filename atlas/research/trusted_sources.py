from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class TrustedSource:
    source_id: str
    name: str
    url: str
    tier: int
    domains: tuple[str, ...]
    audiences: tuple[str, ...]
    cadence: str
    notes: str = ""

# Tier 1 = primary public institutions. Tier 2 = professional/public research.
# Copyrighted books are reference metadata only; Atlas never stores or reproduces full text.
TRUSTED_SOURCES: tuple[TrustedSource, ...] = (
    TrustedSource("FED_MPR","Federal Reserve Monetary Policy Report","https://www.federalreserve.gov/monetarypolicy/publications/mpr_default.htm",1,("USD","XAUUSD"),("SUPERVISOR","H4_STRUCTURE","H1_STRUCTURE"),"SEMIANNUAL"),
    TrustedSource("FED_FOMC","Federal Reserve FOMC releases","https://www.federalreserve.gov/newsevents/pressreleases.htm",1,("USD","XAUUSD"),("SUPERVISOR","NEWS"),"EVENT_DRIVEN"),
    TrustedSource("ECB_EB","ECB Economic Bulletin","https://www.ecb.europa.eu/press/economic-bulletin/html/index.en.html",1,("EUR","USD"),("SUPERVISOR","H4_STRUCTURE","H1_STRUCTURE"),"6_WEEKS"),
    TrustedSource("BOC_MPR","Bank of Canada Monetary Policy Report","https://www.bankofcanada.ca/publications/mpr/",1,("CAD","USD"),("SUPERVISOR","H4_STRUCTURE","H1_STRUCTURE"),"QUARTERLY"),
    TrustedSource("BOJ_MPOL","Bank of Japan Monetary Policy releases","https://www.boj.or.jp/en/mopo/mpmdeci/index.htm",1,("JPY","USD"),("SUPERVISOR","H4_STRUCTURE","H1_STRUCTURE"),"EVENT_DRIVEN"),
    TrustedSource("BIS_QR","BIS Quarterly Review","https://www.bis.org/quarterlyreviews/index.htm",1,("GLOBAL_FX","XAUUSD"),("SUPERVISOR","RISK","MARKET_STRUCTURE"),"QUARTERLY"),
    TrustedSource("IMF_GFSR","IMF Global Financial Stability Report","https://www.imf.org/en/publications/gfsr",1,("GLOBAL_FX","XAUUSD"),("SUPERVISOR","RISK"),"SEMIANNUAL"),
    TrustedSource("IMF_WEO","IMF World Economic Outlook","https://www.imf.org/en/publications/weo",1,("GLOBAL_MACRO",),("SUPERVISOR","H4_STRUCTURE"),"QUARTERLY_UPDATE"),
    TrustedSource("JPM_GLOBAL_RESEARCH","J.P. Morgan Global Research","https://www.jpmorgan.com/insights/research",2,("GLOBAL_FX","USD","EUR","JPY","CAD","XAUUSD"),("RESEARCH_EDUCATION_SUPERVISOR",),"WEEKLY","Public research only; never bypass paywalls."),
    TrustedSource("GS_INSIGHTS","Goldman Sachs Insights","https://www.goldmansachs.com/insights/",2,("GLOBAL_FX","USD","EUR","JPY","CAD","XAUUSD"),("RESEARCH_EDUCATION_SUPERVISOR",),"WEEKLY","Public research only; never bypass paywalls."),
    TrustedSource("UBS_CIO_FX","UBS CIO View - Currencies","https://www.ubs.com/global/en/wealthmanagement/insights/fx-report.html",2,("GLOBAL_FX","USD","EUR","JPY","CAD","XAUUSD"),("RESEARCH_EDUCATION_SUPERVISOR",),"WEEKLY","Public research only; advisory context, never a trade signal."),
)

BOOK_REFERENCES: tuple[dict[str, str], ...] = (
    {"title":"Technical Analysis of the Financial Markets","author":"John J. Murphy","use":"Terminology and classical technical-analysis reference; metadata/principles only."},
    {"title":"Technical Analysis of Stock Trends","author":"Robert D. Edwards, John Magee, W.H.C. Bassetti","use":"Classical chart-pattern reference; metadata/principles only."},
    {"title":"Encyclopedia of Chart Patterns","author":"Thomas N. Bulkowski","use":"Pattern taxonomy/performance reference; metadata/principles only."},
)
