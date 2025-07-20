from pydantic import BaseModel, Field

from velociraptor.llm.gemini import Gemini
from velociraptor.models.attachment import Attachment
from velociraptor.models.page import Page
from velociraptor.models.summary import Summary
from velociraptor.prompts.prompt import extract_and_summarize_page_prompt, summarize_summaries_prompt

llm = Gemini()


def extract_and_summarize_page(page: Page) -> (Page, Summary):
    class PageTextResponse(BaseModel):
        """
        Pydantic model representing the output extracted from a document page.
        """
        full_text: str = Field(description="""
            The full text on the page. Represent tabular data in markdown format.
        """)
        summary: str= Field(description="""
            A complete and thorough summary of the contents of the page.  
            Describe any graphics or tabular data in detail so that the information they convey is captured.
        """)
        has_graphics: bool= Field(description="""
            Indicate whether this page has information represented in graphic form. 
            This could be charts, graphs, pictures, images, drawings, or other forms.
        """)
        has_tabular_data: bool= Field(description="""
            Indicate whether there is tabular data on this page.
        """)

    attach = Attachment(
        file_path=page.file_path,
        mime_type=page.mime_type
    )
    response = llm.prompt(extract_and_summarize_page_prompt(), [attach], PageTextResponse.model_json_schema())
    response_obj = PageTextResponse.model_validate_json(response)
    page.text = response_obj.full_text
    page.has_graphics = response_obj.has_graphics
    page.has_tabular_data = response_obj.has_tabular_data
    summary = Summary(
        document_uuid=page.document_uuid,
        height=page.height + 1,
        position=page.position,
        text=response_obj.summary
    )
    return page, summary


def summarize_summaries(*summaries: Summary, position: int) -> Summary:
    response = llm.prompt(summarize_summaries_prompt(*summaries))
    return Summary(
        document_uuid=summaries[0].document_uuid,
        height=summaries[0].height + 1,
        position=position,
        text=response
    )