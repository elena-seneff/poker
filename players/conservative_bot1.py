"""
Conservative Bot - Plays very tight and safe
Only plays strong hands and folds most of the time
"""
from typing import List, Dict, Any, Tuple

from bot_api import PokerBotAPI, PlayerAction, GameInfoAPI
from engine.cards import Card, Rank, HandEvaluator
from engine.poker_game import GameState


class ConservativeBot(PokerBotAPI):
    """
    A conservative bot that only plays very strong hands.
    Good example of a tight playing style.
    """
    
    def __init__(self, name: str):
        super().__init__(name)
        self.hands_played = 0
        self.hands_won = 0
        
        # Define strong starting hands
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
        """Play very conservatively - only strong hands pre-flop, then evaluate post-flop"""
        
        if game_state.round_name == "preflop":
            return self._preflop_strategy(game_state, hole_cards, legal_actions, min_bet, max_bet)
        else:
            return self._postflop_strategy(game_state, hole_cards, legal_actions, min_bet, max_bet)

    def _preflop_strategy(self, game_state: GameState, hole_cards: List[Card], legal_actions: List[PlayerAction], 
                          min_bet: int, max_bet: int) -> tuple:
        """Strategy for pre-flop betting"""
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
        if PlayerAction.RAISE in legal_actions:
            # Raise 3x the big blind
            raise_amount = min(3 * game_state.big_blind, max_bet)
            raise_amount = max(raise_amount, min_bet)
            return PlayerAction.RAISE, raise_amount
        
        if PlayerAction.CALL in legal_actions:
            return PlayerAction.CALL, 0
            
        return PlayerAction.FOLD, 0

    def _postflop_strategy(self, game_state: GameState, hole_cards: List[Card], 
                           legal_actions: List[PlayerAction], min_bet: int, max_bet: int) -> tuple:
        """Strategy for post-flop betting (flop, turn, river)"""
        
        all_cards = hole_cards + game_state.community_cards
        hand_type, _, _ = HandEvaluator.evaluate_best_hand(all_cards)
        hand_rank = HandEvaluator.HAND_RANKINGS[hand_type]

        # Strong hand (two pair or better)
        if hand_rank >= HandEvaluator.HAND_RANKINGS['two_pair']:
            if PlayerAction.RAISE in legal_actions:
                # Bet half the pot
                raise_amount = min(game_state.pot // 2, max_bet)
                raise_amount = max(raise_amount, min_bet)
                return PlayerAction.RAISE, raise_amount
            if PlayerAction.CALL in legal_actions:
                return PlayerAction.CALL, 0
            return PlayerAction.CHECK, 0

        # Decent hand (pair)
        if hand_rank >= HandEvaluator.HAND_RANKINGS['pair']:
            if PlayerAction.CHECK in legal_actions:
                return PlayerAction.CHECK, 0
            # Call small bets
            to_call = game_state.current_bet - game_state.player_bets[self.name]
            if PlayerAction.CALL in legal_actions and to_call < game_state.pot / 4:
                return PlayerAction.CALL, 0
        
        # Drawing hands
        if self._has_strong_draw(all_cards):
            if PlayerAction.CHECK in legal_actions:
                return PlayerAction.CHECK, 0
            # Call if pot odds are good
            pot_odds = GameInfoAPI.get_pot_odds(game_state.pot, game_state.current_bet - game_state.player_bets[self.name])
            if PlayerAction.CALL in legal_actions and pot_odds > 4: # Need 4:1 for a flush draw
                 return PlayerAction.CALL, 0
            
            return PlayerAction.FOLD, 0

        # Nothing good, fold
        if PlayerAction.CHECK in legal_actions:
            return PlayerAction.CHECK, 0
        return PlayerAction.FOLD, 0

    def _has_strong_draw(self, all_cards: List[Card]) -> bool:
        """Check for strong drawing hands (flush or open-ended straight)"""
        # Flush draw
        suits = [card.suit for card in all_cards]
        for suit in set(suits):
            if suits.count(suit) == 4:
                return True
        
        # Open-ended straight draw
        ranks = sorted(list(set(card.rank.value for card in all_cards)))
        for i in range(len(ranks) - 3):
            if ranks[i+3] - ranks[i] == 3 and len(ranks) >=4 :
                 # e.g., 5,6,7,8
                return True
            # Ace-low straight draw
            if set(ranks).issuperset({2,3,4,5}) or set(ranks).issuperset({14,2,3,4}): # A,2,3,4
                 return True

        return False

    def hand_complete(self, game_state: GameState, hand_result: Dict[str, Any]):
        """Track conservative play results"""
        self.hands_played += 1
        
        if 'winners' in hand_result and self.name in hand_result['winners']:
            self.hands_won += 1
        
        if self.hands_played > 0 and self.hands_played % 25 == 0:
            win_rate = self.hands_won / self.hands_played
            self.logger.info(f"Conservative play: {self.hands_won}/{self.hands_played} wins ({win_rate:.2%})")