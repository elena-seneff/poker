"""
Bot API Interface for Poker Tournament
This defines the interface that all student bots must implement
"""
from abc import ABC, abstractmethod

from bot_api import PokerBotAPI, PlayerAction, GameInfoAPI
from typing import List, Dict, Optional
from engine.cards import Card, Rank, HandEvaluator
from engine.poker_game import GameState
import logging
import random


class HybridBot(PokerBotAPI):
    """
    Hybrid Bot - mixes conservative preflop selection with aggressive postflop and adaptive
    tendencies. Plays tight with strong starting hands but will semi-bluff and raise
    with draws or when table dynamics favour aggression.
    """
    def __init__(self, name: str):
        super().__init__(name)
        self.hands_played = 0
        self.hands_won = 0
        # Aggro/conservative knobs
        self.raise_frequency = 0.5
        self.play_frequency = 0.75

        # Strong starting hands (conservative core)
        self.premium_hands = [
            (Rank.ACE, Rank.ACE), (Rank.KING, Rank.KING), (Rank.QUEEN, Rank.QUEEN),
            (Rank.JACK, Rank.JACK), (Rank.TEN, Rank.TEN),
            (Rank.ACE, Rank.KING), (Rank.ACE, Rank.QUEEN), (Rank.KING, Rank.QUEEN)
        ]

        self.good_suited_connectors = [
            (Rank.KING, Rank.JACK), (Rank.QUEEN, Rank.JACK), (Rank.JACK, Rank.TEN),
            (Rank.TEN, Rank.NINE), (Rank.NINE, Rank.EIGHT)
        ]

    def get_action(self, game_state: GameState, hole_cards: List[Card],
                   legal_actions: List[PlayerAction], min_bet: int, max_bet: int) -> tuple:
        if game_state.round_name == "preflop":
            return self._preflop_strategy(game_state, hole_cards, legal_actions, min_bet, max_bet)
        return self._postflop_strategy(game_state, hole_cards, legal_actions, min_bet, max_bet)

    def _preflop_strategy(self, game_state: GameState, hole_cards: List[Card], legal_actions: List[PlayerAction],
                          min_bet: int, max_bet: int) -> tuple:
        # Safety checks
        if len(hole_cards) != 2:
            return PlayerAction.FOLD, 0

        # Randomly fold a portion of weak hands (aggressive mix)
        if random.random() > self.play_frequency:
            if PlayerAction.CHECK in legal_actions:
                return PlayerAction.CHECK, 0
            return PlayerAction.FOLD, 0

        c1, c2 = hole_cards
        hand1 = (c1.rank, c2.rank)
        hand2 = (c2.rank, c1.rank)

        is_premium = (hand1 in self.premium_hands or hand2 in self.premium_hands)
        is_suited_connector = (c1.suit == c2.suit and (hand1 in self.good_suited_connectors or hand2 in self.good_suited_connectors))
        is_pair = c1.rank == c2.rank

        # Conservative baseline: play only strong hands, but allow occasional loosening
        if not (is_premium or is_suited_connector or is_pair):
            # occasionally limp/call as an aggressive element
            if PlayerAction.CALL in legal_actions and random.random() < 0.12:
                return PlayerAction.CALL, 0
            if PlayerAction.CHECK in legal_actions:
                return PlayerAction.CHECK, 0
            return PlayerAction.FOLD, 0

        # If we have a playable hand, decide to raise occasionally
        if PlayerAction.RAISE in legal_actions and random.random() < self.raise_frequency:
            raise_amount = min(int(random.uniform(2.5, 4.0) * game_state.big_blind), max_bet)
            raise_amount = max(raise_amount, min_bet)
            return PlayerAction.RAISE, raise_amount

        if PlayerAction.CALL in legal_actions:
            return PlayerAction.CALL, 0

        return PlayerAction.CHECK, 0

    def _postflop_strategy(self, game_state: GameState, hole_cards: List[Card], legal_actions: List[PlayerAction],
                           min_bet: int, max_bet: int) -> tuple:
        all_cards = hole_cards + game_state.community_cards
        hand_type, _, _ = HandEvaluator.evaluate_best_hand(all_cards)
        hand_rank = HandEvaluator.HAND_RANKINGS[hand_type]

        # Strong made hands (two pair or better): be aggressive
        if hand_rank >= HandEvaluator.HAND_RANKINGS['two_pair']:
            if PlayerAction.RAISE in legal_actions:
                raise_amount = min(game_state.pot, max_bet)
                raise_amount = max(raise_amount, min_bet)
                return PlayerAction.RAISE, raise_amount
            if PlayerAction.CALL in legal_actions:
                return PlayerAction.CALL, 0
            return PlayerAction.CHECK, 0

        # Top pair / one pair: mostly call or check
        if hand_rank >= HandEvaluator.HAND_RANKINGS['pair']:
            to_call = game_state.current_bet - game_state.player_bets.get(self.name, 0)
            if PlayerAction.CALL in legal_actions and to_call <= game_state.pot // 4:
                return PlayerAction.CALL, 0
            if PlayerAction.CHECK in legal_actions:
                return PlayerAction.CHECK, 0

        # Strong draws: semi-bluff sometimes
        if self._has_strong_draw(all_cards):
            if PlayerAction.RAISE in legal_actions and random.random() < 0.4:
                raise_amount = min(game_state.pot // 2, max_bet)
                raise_amount = max(raise_amount, min_bet)
                return PlayerAction.RAISE, raise_amount
            if PlayerAction.CALL in legal_actions:
                return PlayerAction.CALL, 0

        # If nothing, prefer to check, otherwise fold
        if PlayerAction.CHECK in legal_actions:
            return PlayerAction.CHECK, 0
        return PlayerAction.FOLD, 0

    def _has_strong_draw(self, all_cards: List[Card]) -> bool:
        suits = [c.suit for c in all_cards]
        for s in set(suits):
            if suits.count(s) >= 4:
                return True

        ranks = sorted(list(set(c.rank.value for c in all_cards)))
        if len(ranks) >= 4:
            for i in range(len(ranks) - 3):
                if ranks[i+3] - ranks[i] == 3:
                    return True
        # Ace-low consideration
        rset = set(ranks)
        if rset.issuperset({14, 2, 3, 4}) or rset.issuperset({2,3,4,5}):
            return True
        return False

    def hand_complete(self, game_state: GameState, hand_result: Dict[str, any]):
        self.hands_played += 1
        if 'winners' in hand_result and self.name in hand_result['winners']:
            self.hands_won += 1
            # win -> slightly more aggressive
            self.raise_frequency = min(0.8, self.raise_frequency + 0.02)
            self.play_frequency = min(0.9, self.play_frequency + 0.01)
        else:
            # loss -> tighten up slightly
            self.raise_frequency = max(0.3, self.raise_frequency - 0.01)
            self.play_frequency = max(0.6, self.play_frequency - 0.01)

    def tournament_start(self, players: List[str], starting_chips: int):
        super().tournament_start(players, starting_chips)
        n = len(players)
        if n <= 4:
            self.raise_frequency = 0.6
            self.play_frequency = 0.85
        elif n >= 8:
            self.raise_frequency = 0.45
            self.play_frequency = 0.7


class GameInfoAPI:
    """
    Utility class providing game information and helper methods for bots
    """
    
    @staticmethod
    def get_pot_odds(pot: int, bet_to_call: int) -> float:
        """
        Calculate pot odds as a ratio.
        
        Args:
            pot: Current pot size
            bet_to_call: Amount you need to call
            
        Returns:
            float: Pot odds ratio (pot_size / bet_to_call)
        """
        if bet_to_call == 0:
            return float('inf')
        return pot / bet_to_call
    
    @staticmethod
    def get_position_info(game_state: GameState, player_name: str) -> Dict[str, any]:
        """
        Get position information for a player.
        
        Args:
            game_state: Current game state
            player_name: Name of the player
            
        Returns:
            dict: Position information including:
                - 'position': 0-based position (0 = first to act)
                - 'players_after': Number of players acting after this player
                - 'is_last': True if this player acts last
        """
        try:
            position = game_state.active_players.index(player_name)
            current_pos = game_state.active_players.index(game_state.current_player)
            
            # Adjust position relative to current player
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
        """
        Calculate how much a player needs to call.
        
        Args:
            current_bet: The current highest bet
            player_current_bet: How much the player has already bet this round
            
        Returns:
            int: Amount needed to call
        """
        return max(0, current_bet - player_current_bet)
    
    @staticmethod
    def get_active_opponents(game_state: GameState, player_name: str) -> List[str]:
        """
        Get list of active opponents.
        
        Args:
            game_state: Current game state
            player_name: Name of the player
            
        Returns:
            List[str]: List of opponent names still in the hand
        """
        return [player for player in game_state.active_players if player != player_name]
    
    @staticmethod
    def is_heads_up(game_state: GameState) -> bool:
        """
        Check if the game is heads-up (only 2 players remaining).
        
        Args:
            game_state: Current game state
            
        Returns:
            bool: True if only 2 players remain
        """
        return len(game_state.active_players) == 2
    
    @staticmethod
    def get_stack_sizes(game_state: GameState) -> Dict[str, int]:
        """
        Get effective stack sizes for all players.
        
        Args:
            game_state: Current game state
            
        Returns:
            Dict[str, int]: Player names mapped to their chip counts
        """
        return game_state.player_chips.copy()
    
    @staticmethod
    def format_cards(cards: List[Card]) -> str:
        """
        Format a list of cards for display.
        
        Args:
            cards: List of Card objects
            
        Returns:
            str: Formatted string representation
        """
        return ', '.join(str(card) for card in cards)

    @staticmethod
    def evaluate_hand(all_cards: List[Card]) -> Dict[str, any]:
        """
        Evaluate the best hand and return a dict with type and rank value.
        """
        hand_type, best_hand, hand_info = HandEvaluator.evaluate_best_hand(all_cards)
        rank_value = HandEvaluator.HAND_RANKINGS.get(hand_type, 0)
        return {"hand_type": hand_type, "rank": rank_value, "best_hand": best_hand, "info": hand_info}

    @staticmethod
    def has_flush_draw(all_cards: List[Card]) -> bool:
        """Return True if there is a 4-card flush draw among the provided cards."""
        suits = [c.suit for c in all_cards]
        for s in set(suits):
            if suits.count(s) >= 4:
                return True
        return False

    @staticmethod
    def has_open_ended_straight_draw(all_cards: List[Card]) -> bool:
        """Return True for open-ended straight draws (4 cards to a straight)."""
        ranks = sorted(list(set(c.rank.value for c in all_cards)))
        if len(ranks) < 4:
            return False
        for i in range(len(ranks) - 3):
            if ranks[i+3] - ranks[i] == 3:
                return True
        # Ace-low consideration
        rset = set(ranks)
        if rset.issuperset({14, 2, 3, 4}) or rset.issuperset({2, 3, 4, 5}):
            return True
        return False

    @staticmethod
    def get_draws(all_cards: List[Card]) -> Dict[str, bool]:
        """Convenience aggregator returning detected draw types."""
        return {
            "flush_draw": GameInfoAPI.has_flush_draw(all_cards),
            "straight_draw": GameInfoAPI.has_open_ended_straight_draw(all_cards)
        }

    @staticmethod
    def recommend_aggression(game_state: GameState, player_name: str, all_cards: List[Card]) -> str:
        """
        Recommend a coarse aggression level: 'raise', 'call', or 'check_fold'.
        Uses made-hand rank, draw presence and pot odds to decide.
        """
        evald = GameInfoAPI.evaluate_hand(all_cards)
        rank = evald["rank"]

        # Strong made hands -> raise
        if rank >= HandEvaluator.HAND_RANKINGS.get('two_pair', 2):
            return 'raise'

        # Top pair / pair -> call unless bet is large
        if rank >= HandEvaluator.HAND_RANKINGS.get('pair', 1):
            to_call = game_state.current_bet - game_state.player_bets.get(player_name, 0)
            if to_call <= game_state.pot // 3:
                return 'call'
            return 'check_fold'

        # Draws: semi-bluff if pot odds and position look favourable
        draws = GameInfoAPI.get_draws(all_cards)
        if draws['flush_draw'] or draws['straight_draw']:
            to_call = game_state.current_bet - game_state.player_bets.get(player_name, 0)
            pot_odds = GameInfoAPI.get_pot_odds(game_state.pot, to_call)
            pos = GameInfoAPI.get_position_info(game_state, player_name)
            # favourable if pot odds > 3:1 or acting last
            if pot_odds >= 3 or pos.get('is_last', False):
                return 'raise'
            return 'call'

        return 'check_fold'

