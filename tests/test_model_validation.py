import copy
import json
import os
import unittest
from unittest.mock import patch

import test_app as fixtures
from zizai import deepseek
from zizai.core import Problem


class MessageValidationTests(unittest.TestCase):
    def test_discouraging_compensation_is_allowed(self):
        for phrase in ('无需补偿运动', '不用进行补偿运动', '不建议补偿运动', '不需要额外安排补偿运动'):
            with self.subTest(phrase=phrase):
                self.assertEqual(deepseek.validate_message(phrase), phrase)

    def test_positive_advice_and_unsupported_numbers_remain_blocked(self):
        for phrase in ('建议补偿运动', '安排补偿运动', '今晚只吃300千卡',
                       '无需补偿运动，但是建议补偿运动', '跳过晚餐', '尝试断食'):
            with self.subTest(phrase=phrase), self.assertRaises(ValueError):
                deepseek.validate_message(phrase)

    def test_exception_details_are_not_exposed(self):
        self.assertNotIn('private', deepseek.validation_reason(ValueError('private')))
        try:
            json.loads('private-user-output')
        except json.JSONDecodeError as exc:
            self.assertNotIn('private-user-output', deepseek.validation_reason(exc))


class ModelValidationTests(unittest.TestCase):
    def setUp(self):
        # Reuse the established synthetic fixtures, not a personal database.
        self.fixture = fixtures.DeepSeekTests()
        self.fixture.setUp()

    def test_legitimate_message_passes_without_retry(self):
        f = self.fixture
        data = copy.deepcopy(f.valid)
        data['message'] = '今天可以休息，无需补偿运动。'
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only'}), patch('urllib.request.urlopen', return_value=f.response(data)) as network:
            result = deepseek.recommend(f.p, f.pools, f.reference)
        self.assertEqual(result['message'], data['message'])
        self.assertEqual(network.call_count, 1)

    def test_unknown_option_has_specific_error_and_targeted_retry(self):
        f = self.fixture
        data = copy.deepcopy(f.valid)
        data['choices']['dinner'] = 'not-a-real-option'
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only'}), patch('urllib.request.urlopen', side_effect=[f.response(data), f.response(data)]) as network:
            with self.assertRaises(Problem) as caught:
                deepseek.recommend(f.p, f.pools, f.reference)
        self.assertEqual(caught.exception.code, 'invalid_model_output')
        self.assertIn('不存在的方案ID', str(caught.exception))
        retry = json.loads(network.call_args[0][0].data)['messages'][-1]['content']
        self.assertIn('不存在的方案ID', retry)
        self.assertNotIn('not-a-real-option', retry)


if __name__ == '__main__':
    unittest.main()
