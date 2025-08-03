#!/usr/bin/env python3

import asyncio
import sys

from velociraptor.scripts.rawr import rawr
from velociraptor.utils.logger import get_logger

logger = get_logger(__name__)


class VelociraptorREPL:
    """A REPL terminal interface for Velociraptor that maintains conversation context."""
    
    def __init__(self) -> None:
        self.continue_conversation: bool = False
        self.session_active: bool = True
        
    def print_welcome(self) -> None:
        """Print welcome message and instructions."""
        print("Velociraptor REPL")
        print("Type your prompts and press Enter. Use /clear to start a new conversation.")
        print("Press Ctrl+C or Ctrl+D to exit.")
        print("-" * 50)
        
    def print_prompt(self) -> None:
        """Print the input prompt."""
        print("\n> ", end="", flush=True)
        
    def handle_slash_command(self, command: str) -> bool:
        """
        Handle slash commands.
        
        Args:
            command: The command string (including the /)
            
        Returns:
            True if command was handled, False otherwise
        """
        if command.strip() == "/clear":
            self.continue_conversation = False
            print("Context cleared. Starting new conversation.")
            return True
        elif command.strip() in ["/help", "/?"]:
            print("Available commands:")
            print("  /clear - Clear conversation context and start new session")
            print("  /help  - Show this help message")
            print("  Ctrl+C or Ctrl+D - Exit")
            return True
        else:
            print(f"Unknown command: {command}")
            print("Use /help to see available commands.")
            return True
            
    async def process_input(self, user_input: str) -> None:
        """
        Process user input and get response from rawr.
        
        Args:
            user_input: The user's input string
        """
        try:
            print("\nThinking...")
            response = await rawr(user_input, continue_conversation=self.continue_conversation)
            print(f"\n{response}")
            
            # After first successful interaction, continue conversation
            self.continue_conversation = True
            
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"Error processing input: {e}", exc_info=True)
            print(f"\nError: {e}")
            print("Please try again or use /clear to start fresh.")
    
    async def run(self) -> None:
        """Main REPL loop."""
        self.print_welcome()
        
        try:
            while self.session_active:
                self.print_prompt()
                
                try:
                    user_input = input().strip()
                    
                    if not user_input:
                        continue
                        
                    # Handle slash commands
                    if user_input.startswith("/"):
                        self.handle_slash_command(user_input)
                        continue
                    
                    # Process regular input
                    await self.process_input(user_input)
                    
                except EOFError:
                    # Ctrl+D pressed
                    break
                except KeyboardInterrupt:
                    # Ctrl+C pressed
                    print("\n\nGoodbye!")
                    break
                    
        except Exception as e:
            logger.error(f"Unexpected error in REPL: {e}", exc_info=True)
            print(f"\nUnexpected error: {e}")
        
        print("\nSession ended.")


async def main() -> None:
    """Entry point for the REPL application."""
    repl = VelociraptorREPL()
    await repl.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Failed to start REPL: {e}", exc_info=True)
        print(f"Failed to start REPL: {e}")
        sys.exit(1)