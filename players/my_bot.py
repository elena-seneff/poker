from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any, Tuple
# Assuming 'engine' and 'bot_api' are available in the execution environment
from engine.poker_game import GameState, PlayerAction
import logging
import random
# Using bot_api classes directly
from bot_api import PokerBotAPI, PlayerAction, GameInfoAPI
from engine.cards import Card, Rank, HandEvaluator


class MyBot(PokerBotAPI):
    """
    The main poker bot implementing the required strategy methods.
    """
    
    def __init__(self, name: str):
        super().__init__(name)
        self.hands_played = 0
        self.hands_won = 0
        self.name = name
        self.logger = logging.getLogger(f"bot.{name}")
        # Initialize properties that may be accessed by parent or adaptive logic
        self.raise_frequency = 0.5 
        self.play_frequency = 0.75

        self.premium_hands = [
            (Rank.ACE, Rank.ACE), (Rank.KING, Rank.KING), (Rank.QUEEN, Rank.QUEEN),
            (Rank.JACK, Rank.JACK), (Rank.TEN, Rank.TEN),
            (Rank.ACE, Rank.KING), (Rank.ACE, Rank.QUEEN), (Rank.ACE, Rank.JACK),
            (Rank.KING, Rank.QUEEN)
        ]
        self.good_suited_connectors = [
            (Rank.KING, Rank.JACK), (Rank.QUEEN, Rank.JACK), (Rank.JACK, Rank.TEN),
            (Rank.TEN, Rank.NINE), (Rank.NINE, Rank.EIGHT)
        ]
    
    def get_action(self, game_state: GameState, hole_cards: List[Card], 
                   legal_actions: List[PlayerAction], min_bet: int, max_bet: int) -> tuple:
    
        if game_state.round_name == "preflop":
            return self._preflop_strategy(game_state, hole_cards, legal_actions, min_bet, max_bet)
        else:
            return self._postflop_strategy(game_state, hole_cards, legal_actions, min_bet, max_bet)

    def _preflop_strategy(self, game_state: GameState, hole_cards: List[Card], legal_actions: List[PlayerAction], 
                          min_bet: int, max_bet: int) -> tuple:
        
        if len(hole_cards) != 2:
            return PlayerAction.FOLD, 0
        
        card1, card2 = hole_cards
        hand_tuple1 = (card1.rank, card2.rank)
        hand_tuple2 = (card2.rank, card1.rank)
        
        is_premium = (hand_tuple1 in self.premium_hands or hand_tuple2 in self.premium_hands)
        is_suited_connector = (card1.suit == card2.suit and 
                               (hand_tuple1 in self.good_suited_connectors or 
                                hand_tuple2 in self.good_suited_connectors))
        is_pocket_pair = card1.rank == card2.rank

        if not (is_premium or is_suited_connector or is_pocket_pair):
            if PlayerAction.CHECK in legal_actions:
                return PlayerAction.CHECK, 0
            return PlayerAction.FOLD, 0
            
        # With a good hand, either raise or call
        if PlayerAction.RAISE in legal_actions and random.random() < self.raise_frequency:
            # Raise 3x the big blind
            raise_amount = min(3 * game_state.big_blind, max_bet)
            raise_amount = max(raise_amount, min_bet)
            return PlayerAction.RAISE, raise_amount
        
        if PlayerAction.CALL in legal_actions:
            return PlayerAction.CALL, 0
            
        return PlayerAction.CHECK, 0
    

    def _postflop_strategy(self, game_state: GameState, hole_cards: List[Card], 
                          legal_actions: List[PlayerAction], min_bet: int, max_bet: int) -> tuple:

        all_cards = hole_cards + game_state.community_cards
        # This requires the HandEvaluator class to be defined/available
        hand_type, _, _ = HandEvaluator.evaluate_best_hand(all_cards)
        hand_rank = HandEvaluator.HAND_RANKINGS[hand_type]

        # Strong hand (pair or better, assuming 'pair' is the lowest ranked made hand)
        if hand_rank >= HandEvaluator.HAND_RANKINGS['pair']:
            if PlayerAction.RAISE in legal_actions:
                # Bet 2/3 to full pot
                raise_amount = min(int(game_state.pot * 0.75), max_bet)
                raise_amount = max(raise_amount, min_bet)
                return PlayerAction.RAISE, raise_amount
            if PlayerAction.CALL in legal_actions:
                return PlayerAction.CALL, 0
        
        # Strong draw - play aggressively (semi-bluff)
        if self._has_strong_draw(all_cards):
            if PlayerAction.RAISE in legal_actions:
                # Bet half pot on a draw
                raise_amount = min(game_state.pot // 2, max_bet)
                raise_amount = max(raise_amount, min_bet)
                return PlayerAction.RAISE, raise_amount
            if PlayerAction.CALL in legal_actions:
                return PlayerAction.CALL, 0

        # Bluffing opportunity?
        # If no one has bet, take a stab at the pot
        if game_state.current_bet == 0 and PlayerAction.RAISE in legal_actions:
            bluff_raise = min(game_state.pot // 2, max_bet)
            bluff_raise = max(bluff_raise, min_bet)
            if random.random() < 0.25: # Bluff 25% of the time
                return PlayerAction.RAISE, bluff_raise

        if PlayerAction.CHECK in legal_actions:
            return PlayerAction.CHECK, 0
        
        return PlayerAction.FOLD, 0
    
    def _has_strong_draw(self, all_cards: List[Card]) -> bool:
        # Flush draw (4 cards of the same suit)
        suits = [card.suit for card in all_cards]
        for suit in set(suits):
            if suits.count(suit) >= 4:
                return True
        
        # Open-ended straight draw (4 cards in a row)
        ranks = sorted(list(set(card.rank.value for card in all_cards)))
        
        # Check for 4-card sequence (includes Ace high/low)
        # Check standard straight draws
        for i in range(len(ranks) - 3):
            if ranks[i+3] - ranks[i] == 3:
                return True
        
        # Check wheel straight draw (A-2-3-4 or 2-3-4-5) - assuming Ace=14
        has_wheel = (set([14, 2, 3, 4]).issubset(ranks) or set([2, 3, 4, 5]).issubset(ranks))
        if has_wheel:
            return True

        return False

    def hand_complete(self, game_state: GameState, hand_result: Dict[str, any]):
        self.hands_played += 1

        if 'winners' in hand_result and self.name in hand_result['winners']:
            # Won - increase raise frequency
            self.raise_frequency = min(0.7, self.raise_frequency + 0.02)
        else:
            # Lost - decrease raise frequency
            self.raise_frequency = max(0.3, self.raise_frequency - 0.01)
    
    def tournament_start(self, players: List[str], starting_chips: int):

        super().tournament_start(players, starting_chips)
        num_players = len(players)
        if num_players <= 4:
            self.raise_frequency = 0.6
            self.play_frequency = 0.9
        elif num_players >= 8:
            self.raise_frequency = 0.4
            self.play_frequency = 0.7
    
    def tournament_end(self, final_standings: List[tuple]):
       
        placement = next(place for name, chips, place in final_standings if name == self.name)
        self.logger.info(f"Tournament ended. Final placement: {placement}")


class GameInfoAPI:
    
    @staticmethod
    def get_pot_odds(pot: int, bet_to_call: int) -> float:
        """Calculate pot odds as a ratio."""
        if bet_to_call == 0:
            return float('inf')
        return pot / bet_to_call
    
    @staticmethod
    def get_position_info(game_state: GameState, player_name: str) -> Dict[str, any]:
       
        try:
            position = game_state.active_players.index(player_name)
            current_pos = game_state.active_players.index(game_state.current_player)
            relative_pos = (position - current_pos) % len(game_state.active_players)
            
            return {
                'position': relative_pos,
                'players_after': len(game_state.active_players) - relative_pos - 1,
                'is_last': relative_pos == len(game_state.active_players) - 1
            }
        except ValueError:
            return {'position': -1, 'players_after': 0, 'is_last': False}
    
    @staticmethod
    def calculate_bet_amount(current_bet: int, player_current_bet: int) -> int:
        """Calculate how much a player needs to call."""
        return max(0, current_bet - player_current_bet)
    
    @staticmethod
    def get_active_opponents(game_state: GameState, player_name: str) -> List[str]:
        """Get list of active opponents."""
        return [player for player in game_state.active_players if player != player_name]
    
    @staticmethod
    def is_heads_up(game_state: GameState) -> bool:
        """Check if the game is heads-up (only 2 players remaining)."""
        return len(game_state.active_players) == 2
    
    @staticmethod
    def get_stack_sizes(game_state: GameState) -> Dict[str, int]:
        """Get effective stack sizes for all players."""
        return game_state.player_chips.copy()
    
    @staticmethod
    def format_cards(cards: List[Card]) -> str:
        """Format a list of cards for display."""
        return ', '.join(str(card) for card in cards)