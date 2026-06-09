"""CBT cognitive distortion detector — V2.

Detects common cognitive distortions in user speech:
  - catastrophizing (灾难化)
  - black-and-white thinking (黑白思维)
  - overgeneralization (过度概括)
  - negative self-labeling (自我否定)

Returns is_negative_schema flag and reframed narrative.
"""


def detect_distortions(text: str) -> list[dict]:
    """Keyword-based fast screening (V2 adds LLM-based detection).

    Returns list of {raw_text, detected_distortion, reframed}.
    """
    patterns = [
        ("全搞砸了|彻底完了|永远不行|完全没用", "catastrophizing"),
        ("从来都|每次都|永远不会|总是", "overgeneralization"),
        ("我就是|我这个人就|我太", "negative_self_labeling"),
        ("要么.*要么|不是.*就是", "black_and_white"),
    ]
    import re

    results = []
    for pattern, distortion in patterns:
        if re.search(pattern, text):
            results.append({
                "raw_text": text,
                "detected_distortion": distortion,
                "is_negative_schema": True,
            })
    return results


def reframe(text: str, distortion: str) -> str:
    """Generate a CBT-reframed third-person narrative (V2: LLM-powered)."""
    reframes = {
        "catastrophizing": f"用户表达了强烈的挫败感和灾难化倾向。需要关注其情绪并帮助客观评估情境。",
        "overgeneralization": f"用户使用了过度概括的语言模式。帮助其聚焦具体事件的特定性。",
        "negative_self_labeling": f"用户出现了负面自我标签化的表达。引导其看到自身能力和过往成就。",
        "black_and_white": f"用户表现出非黑即白的思维模式。帮助其看到中间地带和其他可能性。",
    }
    return reframes.get(distortion, f"需要CBT叙事重构: {text[:50]}...")
