from typing import Optional
from langchain.tools import tool
import http.client
import json
import re
from app.core.config import RAPIDAPI_KEY, RAPIDAPI_HOST
def extract_profile_id(url: str) -> Optional[str]:
    """Extract profile ID from LinkedIn URL."""
    print(f"[LinkedIn] Attempting to extract profile ID from: {url}")
    # Matches linkedin.com/in/profile-id or linkedin.com/company/profile-id
    match = re.search(r'linkedin\.com/(?:in|company)/([^/?#]+)', url)
    if match:
        profile_id = match.group(1)
        print(f"[LinkedIn] Extracted Profile ID: {profile_id}")
        return profile_id
    print(f"[LinkedIn] Failed to extract profile ID from: {url}")
    return None

@tool
def fetch_linkedin_data(linkedin_url: str) -> str:
    """
    Fetch LinkedIn profile activities and data using a LinkedIn URL.
    This tool extracts the profile ID from the URL and retrieves recent activities.
    """
    print(f"[LinkedIn] fetch_linkedin_data called with URL: {linkedin_url}")
    profile_id = extract_profile_id(linkedin_url)
    if not profile_id:
        error_msg = f"Error: Could not extract profile ID from URL: {linkedin_url}"
        print(f"[LinkedIn] {error_msg}")
        return error_msg

    conn = http.client.HTTPSConnection(RAPIDAPI_HOST)

    headers = {
        'x-rapidapi-key': RAPIDAPI_KEY,
        'x-rapidapi-host': RAPIDAPI_HOST
    }

    try:
        # Using the endpoint provided by user
        path = f"/activities/people?profile_id={profile_id}&bypass_cache=false&page=1&content_type=all&count=10"
        print(f"[LinkedIn] Requesting data from: {path}")
        conn.request("GET", path, headers=headers)

        res = conn.getresponse()
        print(f"[LinkedIn] Response Status: {res.status} {res.reason}")
        data = res.read()
        
        decoded_data = data.decode("utf-8")
        # print(f"[LinkedIn] Raw Data: {decoded_data[:500]}...") # Limit log size
        
        # Parse and pre-format the data for the agent
        raw_json = json.loads(decoded_data)
        
        print(f"[LinkedIn] Data parsed successfully. Type: {type(raw_json)}")
        
        formatted_data = f"LinkedIn Profile Context for {profile_id}:\n"
        formatted_data += json.dumps(raw_json, indent=2)
        
        return formatted_data
    except Exception as e:
        error_msg = f"Error fetching LinkedIn data: {str(e)}"
        print(f"[LinkedIn] {error_msg}")
        import traceback
        traceback.print_exc()
        return error_msg
    finally:
        conn.close()
