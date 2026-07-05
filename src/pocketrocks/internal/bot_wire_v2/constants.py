# Generated upstream in PocketRocks shared protocol. Vendored here for public SDK use.
bot_wire_protocol_version = 2

bot_wire_message_kinds = {
    "heartbeatRequest": 1,
    "heartbeatResponse": 2,
    "decisionRequest": 3,
    "decisionResponse": 4,
}

bot_wire_decision_kinds = {
    "submitBid": 1,
    "selectInfoToReveal": 2,
}

bot_wire_response_action_kinds = {
    "pass": 1,
    "submitBid": 2,
    "selectInfoToReveal": 3,
}

bot_wire_event_kinds = {
    "gameSetup": 1,
    "turnOpened": 2,
    "auctionResolved": 3,
    "infoRevealed": 4,
}

bot_wire_action_ids = {
    "Auction1": 1,
    "Auction2": 2,
    "Loan10": 3,
    "Loan20": 4,
    "Invest5": 5,
    "Invest10": 6,
}

bot_wire_objective_ids = {
    "prod-any-same2": 1,
    "prod-any-same3": 2,
    "prod-any-different3": 3,
    "prod-any-different4": 4,
    "prod-any-two-pairs4": 5,
    "prod-spec-same2-s1": 6,
    "prod-spec-same2-s2": 7,
    "prod-spec-same2-s3": 8,
    "prod-spec-same2-s4": 9,
    "prod-spec-same2-s5": 10,
    "prod-spec-diff2-12": 11,
    "prod-spec-diff2-13": 12,
    "prod-spec-diff2-14": 13,
    "prod-spec-diff2-15": 14,
    "prod-spec-diff2-23": 15,
    "prod-spec-diff2-24": 16,
    "prod-spec-diff2-25": 17,
    "prod-spec-diff2-34": 18,
    "prod-spec-diff2-35": 19,
    "prod-spec-diff2-45": 20,
    "prod-spec-diff3-123": 21,
    "prod-spec-diff3-124": 22,
    "prod-spec-diff3-125": 23,
    "prod-spec-diff3-134": 24,
    "prod-spec-diff3-135": 25,
    "prod-spec-diff3-145": 26,
    "prod-spec-diff3-234": 27,
    "prod-spec-diff3-235": 28,
    "prod-spec-diff3-245": 29,
    "prod-spec-diff3-345": 30,
}

bot_wire_objective_definitions = {
    "1": {"id": "prod-any-same2", "wireId": 1, "pattern": "same2"},
    "2": {"id": "prod-any-same3", "wireId": 2, "pattern": "same3"},
    "3": {"id": "prod-any-different3", "wireId": 3, "pattern": "different3"},
    "4": {"id": "prod-any-different4", "wireId": 4, "pattern": "different4"},
    "5": {"id": "prod-any-two-pairs4", "wireId": 5, "pattern": "twoPairs4"},
    "6": {"id": "prod-spec-same2-s1", "wireId": 6, "requirement": [2, 0, 0, 0, 0]},
    "7": {"id": "prod-spec-same2-s2", "wireId": 7, "requirement": [0, 2, 0, 0, 0]},
    "8": {"id": "prod-spec-same2-s3", "wireId": 8, "requirement": [0, 0, 2, 0, 0]},
    "9": {"id": "prod-spec-same2-s4", "wireId": 9, "requirement": [0, 0, 0, 2, 0]},
    "10": {"id": "prod-spec-same2-s5", "wireId": 10, "requirement": [0, 0, 0, 0, 2]},
    "11": {"id": "prod-spec-diff2-12", "wireId": 11, "requirement": [1, 1, 0, 0, 0]},
    "12": {"id": "prod-spec-diff2-13", "wireId": 12, "requirement": [1, 0, 1, 0, 0]},
    "13": {"id": "prod-spec-diff2-14", "wireId": 13, "requirement": [1, 0, 0, 1, 0]},
    "14": {"id": "prod-spec-diff2-15", "wireId": 14, "requirement": [1, 0, 0, 0, 1]},
    "15": {"id": "prod-spec-diff2-23", "wireId": 15, "requirement": [0, 1, 1, 0, 0]},
    "16": {"id": "prod-spec-diff2-24", "wireId": 16, "requirement": [0, 1, 0, 1, 0]},
    "17": {"id": "prod-spec-diff2-25", "wireId": 17, "requirement": [0, 1, 0, 0, 1]},
    "18": {"id": "prod-spec-diff2-34", "wireId": 18, "requirement": [0, 0, 1, 1, 0]},
    "19": {"id": "prod-spec-diff2-35", "wireId": 19, "requirement": [0, 0, 1, 0, 1]},
    "20": {"id": "prod-spec-diff2-45", "wireId": 20, "requirement": [0, 0, 0, 1, 1]},
    "21": {"id": "prod-spec-diff3-123", "wireId": 21, "requirement": [1, 1, 1, 0, 0]},
    "22": {"id": "prod-spec-diff3-124", "wireId": 22, "requirement": [1, 1, 0, 1, 0]},
    "23": {"id": "prod-spec-diff3-125", "wireId": 23, "requirement": [1, 1, 0, 0, 1]},
    "24": {"id": "prod-spec-diff3-134", "wireId": 24, "requirement": [1, 0, 1, 1, 0]},
    "25": {"id": "prod-spec-diff3-135", "wireId": 25, "requirement": [1, 0, 1, 0, 1]},
    "26": {"id": "prod-spec-diff3-145", "wireId": 26, "requirement": [1, 0, 0, 1, 1]},
    "27": {"id": "prod-spec-diff3-234", "wireId": 27, "requirement": [0, 1, 1, 1, 0]},
    "28": {"id": "prod-spec-diff3-235", "wireId": 28, "requirement": [0, 1, 1, 0, 1]},
    "29": {"id": "prod-spec-diff3-245", "wireId": 29, "requirement": [0, 1, 0, 1, 1]},
    "30": {"id": "prod-spec-diff3-345", "wireId": 30, "requirement": [0, 0, 1, 1, 1]},
}
