import tiktoken

def count_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    """
    Count the number of tokens in a given text for a specified model.

    Args:
        text (str): The input text to be tokenized.
        model (str): The model name to determine the tokenization scheme. Default is "gpt-3.5-turbo".

    Returns:
        int: The number of tokens in the input text.
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
    except KeyError:
        encoding = tiktoken.get_encoding("cl100k_base")
    
    tokens = encoding.encode(text)
    return len(tokens)

def get_maximum_tokens(model: str = "gpt-3.5-turbo") -> int:
    """
    Get the maximum number of tokens allowed for a specified model.

    Args:
        model (str): The model name to determine the maximum token limit. Default is "gpt-3.5-turbo".

    Returns:
        int: The maximum number of tokens allowed for the specified model.
    """
    model_token_limits = {
        "gpt-3.5-turbo": 16385,
        "gpt-4o": 128000
        # Add more models and their token limits as needed
    }
    
    return model_token_limits.get(model, 4096)  # Default to 4096 if model not found