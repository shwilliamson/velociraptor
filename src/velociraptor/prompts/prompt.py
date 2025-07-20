from velociraptor.models.summary import Summary


ADMONISHMENT_BLURB = """
        Limit your response to the requested information. 
        Do not take liberties or make things up. Adhere to the information you are provided. 
        Do not provide any superfluous expository narrative about your process or polite banter back to the me in response to my prompt.
        Many of these such prompts are being submitted in bulk and processed via an automated process.  
"""

USAGE_BLURB = """
        This information will be indexed for both keyword and semantic search.  It will be stored in a hierarchical neo4j 
        graph database that preserves the structural relationship of the document. Each document in the db forms a 
        summarization tree that aggregates page-level, detailed summaries at the leaf nodes up to higher-level, broader summaries 
        eventually reaching a root node representing the overall document. 
        
        An AI agent will later be using these indexes to locate summary nodes at the appropriate level of specificity to answer end-user questions.  
        This AI agent will be able to navigate vertically and laterally between nodes in the document graph to obtain any additional context 
        from the document that is needed to provide thorough, complete and accurate answers.  Hopefully this gives you a clearer 
        picture of how the information you are extracting will be used.
"""

def extract_and_summarize_page_prompt() -> str:
    return f"""
        You are given an image of a single page from a (potentially large) document.
        You are tasked with responding with structured output that provides key information about the contents of the page.
        The extracted text and summary should be as complete and accurate as possible.  
        
        {USAGE_BLURB}
        
        {ADMONISHMENT_BLURB}
    """

def summarize_summaries_prompt(*summaries: Summary) -> str:
    summaries_text = [f"- Summary #{idx+1}:\n\n{s.text}\n\n" for idx, s in enumerate(summaries)]
    return f"""
        You are given several summaries below, each of of which summarizes a sequential page of a document. 
        Your task is to further summarize these summaries into a single higher-level summary. 
        Ensure that the response you produce is succinct yet thorough and distills the key points from each lower level summary.
        However, the summary you produce should be shorter than the aggregate length of the summaries provided below, 
        no more than a few paragraphs. Attempt to preserve high-level concepts in the summary. 
        
        {USAGE_BLURB}
        
        {ADMONISHMENT_BLURB}
        

        {summaries_text}
    """