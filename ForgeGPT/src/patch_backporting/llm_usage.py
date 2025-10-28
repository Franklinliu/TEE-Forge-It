# The recorder of LLM usage for cost tracking and analysis
import os
import json
from datetime import datetime

from git import Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage

class LLMUsageRecorder: 
    """Record LLM usage for cost tracking and analysis.

    Responsibilities:
      - Cache the usage of each LLM's response message using ChatOpenAI client.
      - Provide usage summaries and reports.
    """
    def __init__(self):
        self.usage_data = []  # List to store usage records
        self.start_time = datetime.now().isoformat()
        self.end_time = None
        self.total_tokens = 0
        self.total_cost = 0.0
        self.cost_per_million_input_tokens = {
            "gpt-3.5-turbo": 0.5,  # Example cost per million input tokens
            "gpt-4o-mini": 0.15,    # Example cost per million input tokens
            "gpt-4o": 2.5            # Example cost per million input tokens
        }
        self.cost_per_million_output_tokens = {
            "gpt-3.5-turbo": 1.5,  # Example cost per
            "gpt-4o-mini": 0.6,    # Example cost per million output tokens
            "gpt-4o": 10            # Example cost per million output tokens
        }

    def record_usage(self, model: Optional[ChatOpenAI], response: BaseMessage):
        """Record the usage from a ChatOpenAI response."""
        if model is not None and hasattr(response, "usage_metadata"):
            usage = response.usage_metadata
            if usage is not None:
                prompt_tokens = usage.get("input_tokens", 0)
                completion_tokens = usage.get("output_tokens", 0)
                total_tokens = usage.get("total_tokens", 0)
                model_name = model.model_name if hasattr(model, "model_name") else "unknown"
                cost_permillion_input = self.cost_per_million_input_tokens.get(model_name, 0.0)
                cost_permillion_output = self.cost_per_million_output_tokens.get(model_name, 0.0)
                cost = (prompt_tokens / 1_000_000) * cost_permillion_input + (completion_tokens / 1_000_000) * cost_permillion_output

                record = {
                    "timestamp": datetime.now().isoformat(),
                    "model": model_name,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "cost": cost
                }
                self.usage_data.append(record)
                self.total_tokens += total_tokens
                self.total_cost += cost
    
    def get_summary(self):
        """Get a summary of the recorded usage."""
        self.end_time = datetime.now().isoformat()
        summary = {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_tokens": self.total_tokens,
            "total_cost": self.total_cost,
            "usage_records": self.usage_data
        }
        return summary
    
    def report(self):
        """Print a summary of the recorded usage."""
        summary = self.get_summary()
        print(f"LLM Usage Summary from {summary['start_time']} to {summary['end_time']}:")
        print(f"  Total Tokens: {summary['total_tokens']}")
        print(f"  Total Cost: ${summary['total_cost']:.4f}")
        print("  Detailed Records:")
        for record in summary['usage_records']:
            print(f"    - [{record['timestamp']}] Model: {record['model']}, Tokens: {record['total_tokens']}, Cost: ${record['cost']:.4f}")
        return summary
        
    