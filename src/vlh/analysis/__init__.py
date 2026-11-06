"""Rule-based lecture content analysis from ASR segments + slides."""

from .build import AnalysisResult, Chapter, build_analysis

__all__ = ["AnalysisResult", "Chapter", "build_analysis"]
