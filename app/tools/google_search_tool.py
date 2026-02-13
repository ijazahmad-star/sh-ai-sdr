from langchain_community.tools import DuckDuckGoSearchRun

def search_google_tool():    
    """
    Create Google Search tool
    """   
    return DuckDuckGoSearchRun()