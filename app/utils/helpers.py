def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    # Approximate pricing per 1M tokens
    pricing = {
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 2.50, "output": 10.00},
    }
    
    # Default to gpt-4o-mini if not found
    model_key = "gpt-4o" if "gpt-4o" in model_name and "mini" not in model_name else "gpt-4o-mini"
    cost_config = pricing.get(model_key, pricing["gpt-4o-mini"])
    
    input_cost = (input_tokens / 1_000_000) * cost_config["input"]
    output_cost = (output_tokens / 1_000_000) * cost_config["output"]
    
    return input_cost + output_cost