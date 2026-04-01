import pytest
from nexus_paper_fetcher.models import Paper


@pytest.fixture
def sample_papers() -> list[Paper]:
    def make(title, doi=None, arxiv_id=None, year=2022, venue=None,
             abstract="Sample abstract text for testing purposes.",
             citation_count=100, sources=None, openreview_tier=None,
             open_access_pdf_url=None, semantic_scholar_id=None, openalex_id=None):
        return Paper.create(
            title=title, doi=doi, arxiv_id=arxiv_id, year=year, venue=venue,
            abstract=abstract, citation_count=citation_count,
            sources=sources or ["openalex"], openreview_tier=openreview_tier,
            open_access_pdf_url=open_access_pdf_url,
            semantic_scholar_id=semantic_scholar_id, openalex_id=openalex_id,
        )

    return [
        make("Gene Expression Analysis via Neural Networks",
             doi="10.1038/s41592-023-001", year=2023, venue="Nature Methods",
             citation_count=412, sources=["openalex"], openalex_id="W111",
             abstract="We present a scalable method for gene expression analysis using neural networks."),
        make("scGPT Foundation Model for Single-Cell",
             arxiv_id="2306.12865", year=2024, venue="NeurIPS",
             citation_count=89, sources=["semantic_scholar"], semantic_scholar_id="ss222",
             open_access_pdf_url="https://arxiv.org/pdf/2306.12865"),
        make("Attention Is All You Need",
             doi="10.48550/arXiv.1706.03762", year=2017, venue="NeurIPS",
             citation_count=85000, sources=["openalex", "semantic_scholar"],
             openreview_tier="oral"),
        make("A Novel Clustering Approach for Single-Cell Data",
             year=2022, venue="Cell", citation_count=50, sources=["openalex"]),
        make("Deep Learning for Genomics",
             doi="10.1038/s41587-021-001", year=2021, venue="Nature Biotechnology",
             citation_count=200, sources=["semantic_scholar"]),
    ]
