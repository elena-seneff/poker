"""
Main Tournament Runner
Orchestrates the entire poker tournament from start to finish
"""
import logging
import sys
import time
import random
from typing import List, Dict, Any, Optional
from datetime import datetime
import json
import os

from engine.poker_game import PokerGame, GameState, PlayerAction
from engine.cards import HandEvaluator
from tournament import PokerTournament, TournamentSettings, TournamentType
from bot_manager import BotManager



class TournamentRunner:
    """Main class that runs the entire poker tournament"""
    
    def __init__(self, settings: TournamentSettings = None, 
                 players_directory: str = "players",
                 log_directory: str = "logs"):
        
        self.settings = settings or TournamentSettings()
        self.players_directory = players_directory
        self.log_directory = log_directory
        
        # Core components
        self.bot_manager = BotManager(players_directory, self.settings.time_limit_per_action)
        self.tournament: Optional[PokerTournament] = None
        self.current_games: Dict[int, PokerGame] = {}  # table_id -> game
        
        # Results tracking
        self.tournament_results: Dict[str, Any] = {}
        self.hand_histories: List[Dict[str, Any]] = []
        
        # Setup logging
        self.setup_logging()
        self.logger = logging.getLogger("tournament_runner")
    
    def setup_logging(self):
        """Configure logging for the tournament"""
        # Create logs directory
        os.makedirs(self.log_directory, exist_ok=True)
        
        # Create timestamp for this tournament
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = os.path.join(self.log_directory, f"tournament_{timestamp}.log")
        
        # Try to ensure console uses UTF-8 to avoid encoding issues with card suits
        try:
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            # Best-effort; if it fails continue without raising
            pass

        # Configure logging with UTF-8 file handler and console stream
        file_handler = logging.FileHandler(log_filename, encoding='utf-8')
        console_handler = logging.StreamHandler(sys.stdout)

        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[file_handler, console_handler]
        )
    
    def run_tournament(self) -> Dict[str, Any]:
        """
        Run the complete tournament from start to finish
        Returns final results dictionary
        """
        self.logger.info("Starting poker tournament...")
        start_time = time.time()
        
        try:
            # Load all bots
            loaded_bots = self.bot_manager.load_all_bots()
            if len(loaded_bots) < 2:
                raise ValueError(f"Need at least 2 bots to run tournament, found {len(loaded_bots)}")
            
            self.logger.info(f"Loaded {len(loaded_bots)} bots: {loaded_bots}")
            
            # Initialize tournament
            self.tournament = PokerTournament(loaded_bots, self.settings)
            
            # Main tournament loop
            while not self.tournament.is_tournament_complete():
                self.run_tournament_round()
                
                # Check for table rebalancing
                if self.tournament.should_rebalance_tables():
                    self.tournament.rebalance_tables()
                    self.logger.info("Tables rebalanced")
            
            # Tournament complete
            final_results = self.tournament.get_final_results()
            end_time = time.time()
            
            
            # Compile final tournament data
            self.tournament_results = {
                'final_standings': final_results,
                'tournament_duration': end_time - start_time,
                'total_hands': self.tournament.current_hand,
                'settings': {
                    'starting_chips': self.settings.starting_chips,
                    'tournament_type': self.settings.tournament_type.value,
                    'blind_levels': f"{self.settings.small_blind}/{self.settings.big_blind}",
                    'time_limit': self.settings.time_limit_per_action
                },
                'bot_stats': self.bot_manager.get_bot_stats(),
            }
            
            self.save_tournament_results()
            self.print_final_results()
            
            return self.tournament_results
            
        except Exception as e:
            self.logger.error(f"Tournament error: {str(e)}")
            raise
        finally:
            self.bot_manager.cleanup()
    
    def run_tournament_round(self):
        """Run one round of hands across all active tables"""
        active_tables = {tid: table for tid, table in self.tournament.tables.items()
                        if len(table.get_active_players()) >= 2}

        # If there are no tables with at least 2 active players, either rebalance
        # or mark the tournament complete to avoid spinning indefinitely.
        if not active_tables:
            active_players = self.tournament.get_active_players()
            # If tournament has 1 or 0 active players, mark complete
            if len(active_players) <= 1:
                self.logger.info("No active tables and <=1 active players — finishing tournament")
                self.tournament.tournament_complete = True
                return

            # Otherwise try rebalancing tables to put players together
            try:
                self.logger.info("No tables with >=2 players — attempting to rebalance tables")
                self.tournament.rebalance_tables()
            except Exception as e:
                self.logger.error(f"Error during rebalance: {e}")
            # Recompute active_tables after rebalance
            active_tables = {tid: table for tid, table in self.tournament.tables.items()
                             if len(table.get_active_players()) >= 2}

            # If still no active tables after rebalance, mark tournament complete
            if not active_tables:
                self.logger.warning("Rebalance did not produce playable tables — ending tournament")
                self.tournament.tournament_complete = True
                return
        
        # Start games on all active tables
        self.current_games = {}
        for table_id, table in active_tables.items():
            player_ids = table.get_active_players()
            if len(player_ids) >= 2:
                small_blind, big_blind = table.get_current_blinds()
                
                bots = {pid: self.bot_manager.get_bot(pid) for pid in player_ids}

                # Create poker game for this table
                game = PokerGame(bots, 
                               starting_chips=0,  # Will use tournament chip counts
                               small_blind=small_blind, 
                               big_blind=big_blind,
                               dealer_button_index=random.randrange(len(bots)))
                
                # Set actual chip counts from tournament
                for player in player_ids:
                    game.player_chips[player] = self.tournament.player_stats[player].chips
                
                self.current_games[table_id] = game
        
        # Play hands on all tables
        for table_id, game in self.current_games.items():
            try:
                self.play_single_hand(table_id, game)
                self.tournament.tables[table_id].dealer_button = game.dealer_button
            except Exception as e:
                self.logger.error(f"Error playing hand on table {table_id}: {str(e)}")
        
        # Advance tournament hand counter
        self.tournament.advance_hand()
    
    def play_single_hand(self, table_id: int, game: PokerGame):
        """Play a single hand of poker on one table"""
        self.logger.info(f"Starting hand #{self.tournament.current_hand + 1} on table {table_id}")
        
        try:
            # The game loop is now handled by the PokerGame itself
            final_chips = game.play_hand()

            # Update tournament chip counts from the game's final state
            for player_id, chips in final_chips.items():
                self.tournament.update_player_chips(player_id, chips)

            self.logger.info(f"Hand #{self.tournament.current_hand + 1} complete on table {table_id}")

        except Exception as e:
            self.logger.error(f"Error in hand on table {table_id}: {str(e)}")
            # Even if a hand fails, we should probably check player chip counts
            # and eliminate those with zero chips. For now, we'll log the error.

    def save_tournament_results(self):
        """Save tournament results to file"""
        if not self.tournament_results:
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = os.path.join(self.log_directory, f"results_{timestamp}.json")
        
        try:
            # Convert results to JSON-serializable format
            serializable_results = self._make_json_serializable(self.tournament_results)
            
            with open(results_file, 'w') as f:
                json.dump(serializable_results, f, indent=2)
            
            self.logger.info(f"Tournament results saved to {results_file}")
        except Exception as e:
            self.logger.error(f"Error saving results: {str(e)}")
    
    def _make_json_serializable(self, data):
        """Convert data to JSON-serializable format"""
        if isinstance(data, dict):
            return {k: self._make_json_serializable(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._make_json_serializable(item) for item in data]
        elif isinstance(data, (str, int, float, bool, type(None))):
            return data
        else:
            return str(data)
    
    def print_final_results(self):
        """Print formatted final results"""
        if not self.tournament_results:
            return
        
        print("\n" + "="*60)
        print("POKER TOURNAMENT RESULTS")
        print("="*60)
        
        standings = self.tournament_results['final_standings']
        for i, (player, chips, position) in enumerate(standings):
            if position == 1:
                print(f"🏆 WINNER: {player} - {chips:,} chips")
            elif position <= 3:
                print(f"🥈 {position}. {player} - {chips:,} chips")
            else:
                print(f"   {position}. {player} - {chips:,} chips")
        
        print("\nTournament Statistics:")
        print(f"Duration: {self.tournament_results['tournament_duration']:.1f} seconds")
        print(f"Total Hands: {self.tournament_results['total_hands']}")
        print(f"Starting Chips: {self.settings.starting_chips:,}")
        
        # Bot statistics
        print("\nBot Performance:")
        for bot_name, stats in self.tournament_results['bot_stats'].items():
            status = "DISQUALIFIED" if stats['is_disqualified'] else "OK"
            print(f"  {bot_name}: {stats['error_count']} errors, " +
                  f"{stats['timeout_count']} timeouts - {status}")
        
        print("="*60 + "\n")


def main():
    """Main entry point for running tournaments"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Run a poker bot tournament')
    parser.add_argument('--players-dir', default='players', 
                       help='Directory containing bot files')
    parser.add_argument('--starting-chips', type=int, default=1000,
                       help='Starting chip count for each player')
    parser.add_argument('--small-blind', type=int, default=10,
                       help='Initial small blind amount')
    parser.add_argument('--big-blind', type=int, default=20,
                       help='Initial big blind amount')
    parser.add_argument('--time-limit', type=float, default=10.0,
                       help='Time limit per action in seconds')
    parser.add_argument('--blind-increase', type=int, default=10,
                       help='Hands between blind increases')
    
    args = parser.parse_args()
    
    # Create tournament settings
    settings = TournamentSettings(
        tournament_type=TournamentType.FREEZE_OUT,
        starting_chips=args.starting_chips,
        small_blind=args.small_blind,
        big_blind=args.big_blind,
        time_limit_per_action=args.time_limit,
        blind_increase_interval=args.blind_increase
    )
    
    # Run tournament
    runner = TournamentRunner(settings, args.players_dir)
    try:
        results = runner.run_tournament()
        print(f"\nTournament completed successfully!")
        print(f"Winner: {results['final_standings'][0][0]}")
    except Exception as e:
        print(f"Tournament failed: {str(e)}")


if __name__ == "__main__":
    main()