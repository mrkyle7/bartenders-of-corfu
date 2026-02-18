#!/usr/bin/env python3

import sys
import os
import unittest
from uuid import uuid4

# Add the src directory to the path so we can import the user module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src', 'bartenders-of-corfu'))

from app.Game import Game

class TestGame(unittest.TestCase):

    def test_game_creation(self):
        host = uuid4()
        players = set()
        players.add(host)
        
        game = Game.new_game(host)
        self.assertSetEqual(game.players, players)
        self.assertListEqual(game.game_state.bag_contents, [])
        self.assertEqual(len(game.game_state.player_states), 1)
        self.assertEqual(game.game_state.player_states[host].player_id, host)