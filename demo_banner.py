"""Demo script to show terminal banner functionality."""

import time
from pokepoke.terminal_ui import set_terminal_banner, format_work_item_banner, clear_terminal_banner


def demo_banner():
    """Demonstrate the terminal banner in action."""
    print("Terminal Banner Demo")
    print("=" * 50)
    print("Look at your PowerShell window title to see the banner!\n")
    
    # Demo 1: Start PokePoke
    print("1. Starting PokePoke...")
    set_terminal_banner("PokePoke Interactive - agent_demo")
    time.sleep(2)
    
    # Demo 2: Working on an item
    print("2. Working on item PokePoke-123...")
    banner = format_work_item_banner("PokePoke-123", "Add terminal banner feature")
    set_terminal_banner(banner)
    time.sleep(2)
    
    # Demo 3: Cleanup phase
    print("3. Running cleanup...")
    banner = format_work_item_banner("PokePoke-123", "Add terminal banner feature", "Cleanup #1")
    set_terminal_banner(banner)
    time.sleep(2)
    
    # Demo 4: Finalizing
    print("4. Finalizing work item...")
    banner = format_work_item_banner("PokePoke-123", "Add terminal banner feature", "Finalizing")
    set_terminal_banner(banner)
    time.sleep(2)
    
    # Demo 5: Beta testing
    print("5. Running beta tests...")
    banner = format_work_item_banner("PokePoke-123", "Add terminal banner feature", "Beta Testing")
    set_terminal_banner(banner)
    time.sleep(2)
    
    # Demo 6: Completed
    print("6. Work item completed!")
    banner = format_work_item_banner("PokePoke-123", "Add terminal banner feature", "Completed")
    set_terminal_banner(banner)
    time.sleep(2)
    
    # Demo 7: Next item
    print("7. Starting next item...")
    banner = format_work_item_banner("PokePoke-456", "This is a very long title that will be truncated to fit in the terminal title bar without overflowing")
    set_terminal_banner(banner)
    time.sleep(2)
    
    # Demo 8: Failed item
    print("8. Simulating failure...")
    banner = format_work_item_banner("PokePoke-456", "This is a very long title that will be truncated", "Failed")
    set_terminal_banner(banner)
    time.sleep(2)
    
    # Demo 9: Clear banner
    print("9. Clearing banner...")
    clear_terminal_banner()
    time.sleep(1)
    
    print("\nDemo complete! The banner has been cleared.")


if __name__ == "__main__":
    demo_banner()
