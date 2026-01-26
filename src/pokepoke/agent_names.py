"""Agent name generation for PokePoke instances."""

import random
import string
from typing import Optional


# Whimsical adjective pool for agent names
ADJECTIVES = [
    "swift", "clever", "mighty", "cosmic", "nimble", "blazing", "quantum",
    "daring", "noble", "wise", "stellar", "rapid", "bright", "keen",
    "bold", "agile", "fierce", "serene", "vibrant", "curious", "zealous",
    "loyal", "brave", "epic", "radiant", "witty", "sharp", "skilled",
    "cunning", "artful", "graceful", "hardy", "valiant", "astute", "savvy"
]

# Pokémon-inspired creature names for fun
CREATURES = [
    "pika", "bulba", "char", "squirtle", "eevee", "drago", "meowth",
    "jigglypuff", "snorlax", "gengar", "lucario", "arcanine", "ninetales",
    "umbreon", "espeon", "vaporeon", "flareon", "jolteon", "alakazam",
    "machamp", "lapras", "gyarados", "charizard", "blastoise", "venusaur",
    "mew", "mewtwo", "pikachu", "raichu", "magikarp", "dugtrio", "golem",
    "onix", "steelix", "scizor", "heracross", "tyranitar", "salamence"
]


def generate_agent_name(prefix: str = "pokepoke") -> str:
    """Generate a random agent name with reasonable entropy.
    
    Format: {prefix}_{adjective}_{creature}_{random_hex}
    Example: pokepoke_swift_pika_a7f3
    
    Args:
        prefix: Prefix for the agent name (default: "pokepoke")
        
    Returns:
        A unique agent name with ~17 bits of entropy from randomness
        (35 adjectives * 38 creatures * 65536 hex = ~87 million combinations)
    """
    adjective = random.choice(ADJECTIVES)
    creature = random.choice(CREATURES)
    
    # 4 hex chars = 16 bits of entropy
    random_suffix = ''.join(random.choices(string.hexdigits.lower(), k=4))
    
    return f"{prefix}_{adjective}_{creature}_{random_suffix}"


def initialize_agent_name(custom_name: Optional[str] = None) -> str:
    """Initialize the agent name for the current run.
    
    If a custom name is provided, use it. Otherwise, generate a random name.
    The name is returned for use in the orchestrator.
    
    Args:
        custom_name: Optional custom agent name to use instead of generating one
        
    Returns:
        The agent name to use for this run
    """
    if custom_name:
        return custom_name
    
    return generate_agent_name()
