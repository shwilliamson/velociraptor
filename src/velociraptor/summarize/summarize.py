from velociraptor.models.page import Page
from velociraptor.models.summary import Summary


def summarize_page(page: Page) -> Summary:
    return Summary(
        document_uuid=page.document_uuid,
        height=page.height + 1,
        position=page.position
    )

def summarize_summaries(*summaries: Summary) -> Summary:
    return Summary(
        document_uuid=summaries[0].document_uuid,
        height=summaries[0].height + 1
    )