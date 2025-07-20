from velociraptor.models.summary import Summary


def extract_and_summarize_page_prompt() -> str:
    return f"""
        You are given an image of a page from a document.
        You are tasked with responding with structured output that provides key information about the contents of the image.
        The extracted text and summary should be as complete and accurate as possible.  Remain faithful to the contents of the image. 
        Do not make up or add any additional content.  Attempt to preserve important or unique keywords and names in the summary 
        as this information will be indexed for both keyword and semantic search.
        
        Do not provide any superfluous expository narrative.  Limit your response to the requested summary.
    """

def summarize_summaries_prompt(*summaries: Summary) -> str:
    summaries_text = [f"Summary #{idx+1}\n{s.text}\n\n" for idx, s in enumerate(summaries)]
    return f"""
        You are given several summaries of sequential portions of a document. 
        Your task is to faithfully synthesize these summaries into a single summary. 
        This is part of a summarization tree that aggregates low level, targeted summaries gradually up to higher level, broad summaries. 
        Ensure that the response you produce is succinct yet thorough and captures the key points from each lower level summary.
        However, do not take liberties or make up information. Adhere to the information you are provided. 
        Attempt to preserve important or unique keywords and names in the summary as this information will be indexed for 
        both keyword and semantic search.
        
        Do not provide any superfluous expository narrative.  Limit your response to the requested summary.
        
        {summaries_text}
    """