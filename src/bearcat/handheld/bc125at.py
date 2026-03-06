"""Contains the class represention of the Uniden BC125AT scanner."""
from enum import Enum
from typing import Tuple, List

from bearcat import Modulation, UnexpectedResultError, Screen, RadioState, Channel, OperationMode, BearcatCommonContrast
from bearcat.handheld import BasicHandheld


class BC125AT(BearcatCommonContrast, BasicHandheld):
    """
    Object for interacting with the Uniden BC125AT serial API. All official and many known unofficial calls are
    supported. See https://info.uniden.com/twiki/pub/UnidenMan4/BC125AT/BC125AT_PC_Protocol_V1.01.pdf for official API.
    """

    AD_SCALING_FACTOR = 255
    TOTAL_CHANNELS = 500
    DISPLAY_WIDTH = 16
    BAUD_RATES = [115200]
    BYTE_MAP = {
        0x80: b'\xe2\x96\x88', 0x81: b'\xe2\x86\x91', 0x82: b'\xe2\x86\x93', 0x83: b'Lo', 0x84: b'Bat', 0x85: b'Lo',
        0x86: b'ck', 0x87: b'C', 0x88: b'C', 0x89: b'C', 0x8A: b'C', 0x8B: b'\xf0\x9f\x84\xb5',
        0x8C: b'\xf0\x9f\x84\xbf', 0x8D: b'H', 0x8E: b'O', 0x8F: b'L', 0x90: b'D', 0x91: b'+',
        0x92: b'\xf0\x9f\x84\xb2', 0x93: b'T', 0x94: b'L', 0x95: b'L', 0x96: b'/', 0x97: b'O', 0x98: b' ', 0x99: b'A',
        0x9A: b'M', 0x9B: b' ', 0x9C: b'F', 0x9D: b'N', 0x9E: b'F', 0x9F: b' ', 0xA0: b' ', 0xA1: b'P', 0xA2: b'RI',
        0xA3: b' ', 0xA4: b' ', 0xA5: b' ', 0xA6: b'1', 0xA7: b'2', 0xA8: b'3', 0xA9: b'\xf0\x9f\x93\xb6', 0xAA: b'4',
        0xAB: b'\xf0\x9f\x93\xb6', 0xAC: b'5', 0xAD: b'\xf0\x9f\x93\xb6', 0xAE: b' ', 0xAF: b' ', 0xB0: b' ',
        0xB1: b'[', 0xB2: b'\xe2\x96\x88', 0xB3: b']', 0xB4: b' ', 0xB5: b'C', 0xB6: b'C', 0xB7: b'C', 0xB8: b'C',
        0xB9: b' ', 0xBA: b' ', 0xBB: b' ', 0xBC: b' ', 0xBD: b' ', 0xBE: b' ', 0xBF: b' ', 0xC0: b' ', 0xC1: b' ',
        0xC2: b' ', 0xC3: b' ', 0xC4: b' ', 0xC5: b'S', 0xC6: b'R', 0xC7: b'C:', 0xC8: b' ', 0xC9: b' ', 0xCA: b' ',
        0xCB: b' ', 0xCC: b' ', 0xCD: b'B', 0xCE: b'N', 0xCF: b'K:', 0xD0: b' ', 0xD1: b' ', 0xD2: b' ', 0xD3: b' ',
        0xD4: b'S', 0xD5: b'V', 0xD6: b'C:', 0xD7: b'D:', 0xD8: b'P', 0xD9: b'R', 0xDA: b'I', 0xDB: b' ', 0xDC: b' ',
        0xDD: b' ', 0xDE: b' ', 0xDF: b' '
    }

    class BacklightMode(Enum):
        """Enumeration of backlight modes supported by the BC125AT."""
        ALWAYS_ON = 'AO'
        ALWAYS_OFF = 'AF'
        KEYPRESS = 'KY'
        SQUELCH = 'SQ'
        KEYPRESS_SQUELCH = 'KS'

    class CloseCallMode(Enum):
        """Enumeration of close call modes supported by the BC125AT."""
        OFF = '0'
        PRIORITY = '1'
        DND = '2'
        ONLY = '3'

    class DelayTime(Enum):
        """Enumeration of allowed delay times."""
        MINUS_TEN = '-10'
        MINUS_FIVE = '-5'
        ZERO = '0'
        ONE = '1'
        TWO = '2'
        THREE = '3'
        FOUR = '4'
        FIVE = '5'

    class TestMode(Enum):
        """Enumeration of various hardware test modes available on the BC125AT."""
        SOFTWARE = '1'
        CLOSE_CALL = '2'
        WEATHER_ALERT = '3'
        KEYPAD = '4'

    @staticmethod
    def compare_channels(a: Channel, b: Channel) -> bool:
        return a.name == b.name and a.frequency == b.frequency and  a.modulation == b.modulation and \
            a.tone_code == b.tone_code and a.delay == b.delay and a.lockout == b.lockout and a.priority == b.priority

    #
    # Getters
    #

    def get_status(self) -> Tuple[Screen, bool, bool]:
        """
        Sends the get status (STS) command. This is an unofficial command for the BC125AT.

        Returns:
            object representation of the scanner's screen
            whether the scanner is squelched
            whether the scanner is muted.
        """
        response = self._execute_command('STS')
        return Screen(*response[:-9]), bool(int(response[-9])), bool(int(response[-8]))

    def get_reception_status(self) -> Tuple[RadioState, bool, bool]:
        """
        Sends the get reception status (GLG) command. This is an unofficial command for the BC125AT.

        Returns:
            object representation of the scanner's radio state
            whether the scanner is squelched
            whether the scanner is muted.
        """
        response = self._execute_command('GLG')
        self._check_response(response, 12)
        state = RadioState(response[9], response[6], int(response[0]) * BC125AT.FREQUENCY_SCALE,
                           Modulation(response[1]), int(response[3]))
        return state, bool(int(response[7])), bool(int(response[8]))

    def get_electronic_serial_number(self) -> Tuple[str, str, str]:
        """
        Sends the get electronic serial number (ESN) command. This appears to be an unofficial and undocumented command
        for all scanners. It also appears to be unused on the BC125AT.

        Returns:
            14 Xs, likely an unused serial number
            3 0s, likely an unused product code
            1
        """
        response = self._execute_command('ESN')
        self._check_response(response, 3)
        return response[0], response[1], response[2]

    #
    # Program Mode Getters
    #

    def get_backlight(self) -> BacklightMode:
        """
        Sends the get backlight (BLT) command. Requires program mode.

        Returns:
            backlight mode as an enumeration
        """
        return BC125AT.BacklightMode(self._get_program_mode_string('BLT'))

    def get_charge_time(self) -> int:
        """
        Sends the get battery info (BSV) command. Requires program mode.

        Returns:
            battery charge time in hours, 1 - 16
        """
        return self._get_program_mode_number('BSV')

    def get_key_beep(self) -> Tuple[bool, bool]:
        """
        Sends the get key beep (KBP) command. Requires program mode.

        Returns:
            whether the keypad beep is enabled
            whether the keypad is locked
        """
        response = self._execute_program_mode_command('KBP')
        self._check_response(response, 2)
        return not bool(int(response[0])), bool(int(response[1]))

    def get_channel_info(self, channel: int) -> Channel:
        """
        Sends the get channel info (CIN) command. Requires program mode.

        Args:
            channel: the channel number to investigate, 1 - 500

        Returns:
            object representation of the channel configuration
        """
        assert 1 <= channel <= BC125AT.TOTAL_CHANNELS
        response = self._execute_program_mode_command('CIN', str(channel))
        self._check_response(response, 8)
        return Channel(int(response[0]), response[1], int(response[2]) * BC125AT.FREQUENCY_SCALE,
                       Modulation(response[3]), int(response[4]), delay=BC125AT.DelayTime(response[5]),
                       lockout=bool(int(response[6])), priority=bool(int(response[7])))

    def get_search_close_call_settings(self) -> Tuple[DelayTime, bool]:
        """
        Sends the get search / close call settings (SCO) command. Requires program mode.

        Returns:
            delay time as an enumeration
            whether CTCSS/DCS code search is enabled
        """
        response = self._execute_program_mode_command('SCO')
        self._check_response(response, 2)
        return BC125AT.DelayTime(response[0]), bool(int(response[1]))

    def get_close_call_settings(self) -> Tuple[CloseCallMode, bool, bool, List[bool], bool]:
        """
        Sends the get close call settings (CLC) command. Requires program mode.

        Returns:
            close call mode as an enumeration
            whether the alert beep is enabled
            whether the alert light is enabled
            a list of 5 bools representing whether each of the 5 close call bands are enabled
            whether scan is unlocked
        """
        response = self._execute_program_mode_command('CLC')
        self._check_response(response, 5)
        return BC125AT.CloseCallMode(response[0]), bool(int(response[1])), bool(int(response[2])),\
            [bool(c) for c in response[3]], bool(int(response[4]))

    def get_service_search_group(self):
        """
        Sends the get service search group (SSG) command. Requires program mode.

        Returns:
            a list of 10 bools representing whether search is enabled for each of the 10 service groups
        """
        return self._get_program_mode_group('SSG')

    def get_weather_priority(self) -> bool:
        """
        Sends the get weather settings (WXS) command. Requires program mode.

        Returns:
            whether weather priority is enabled
        """
        return bool(self._get_program_mode_number('WXS'))

    #
    # Setters
    #

    def jump_to_channel(self, channel: int):
        """
        Jump to number tag (JNT) command. This is an unofficial command for the BC125AT.

        Args:
            channel: channel number
        """
        assert 1 <= channel <= self.TOTAL_CHANNELS, f'Unexpected channel number {channel}, expected 1 - 500'
        self._check_ok(self._execute_command('JNT', '', str(channel - 1)))

    def jump_mode(self, mode: OperationMode):
        """Jump mode (JPM) command. This is an unofficial command for the BC125AT."""
        self._set_value('JPM', mode.value)

    def enter_test_mode(self, mode: TestMode):
        """Enter test mode (TST) command. This appears to be an unofficial and undocumented command for all scanners."""
        assert self._in_program_mode, 'Scanner must be manually put into program mode to use test mode'
        try:
            self._execute_command('TST', mode.value, 'UNIDEN_TEST_MODE')
        except UnexpectedResultError:
            pass
        self._in_program_mode = False

    #
    # Program Mode Setters
    #

    def set_backlight(self, mode: BacklightMode):
        """
        Sends the set backlight (BLT) command. Requires program mode.

        Args:
            mode: enumeration of the desired backlight mode
        """
        self._set_program_mode_value('BLT', mode.value)

    def set_charge_time(self, time: int):
        """
        Sends the set battery setting (BSV) command. Requires program mode despite manual not listing that.

        Args:
            time: battery charge time in hours, 1 - 14
        """
        assert 1 <= time <= 14, f'Unexpected charge time {time}, expected 1 - 14'
        self._set_value('BSV', time)

    def set_key_beep(self, enabled: bool, lock: bool):
        """
        Sends the set key beep (KBP) command. Requires program mode.

        Args:
            enabled: whether keypad beep should be enabled
            lock: whether keypad lock should be enabled
        """
        self._check_ok(self._execute_program_mode_command('KBP', str(int(not enabled) * 99), str(int(lock))))

    def set_channel_info(self, channel: Channel):
        """
        Sends the set channel info (CIN) command. Requires program mode.

        Args:
            channel: object representation of the desired channel parameters
        """
        freq = int(channel.frequency / BC125AT.FREQUENCY_SCALE)
        self._check_ok(self._execute_program_mode_command('CIN', str(channel.index), channel.name, str(freq),
                       channel.modulation.value, str(channel.tone_code), channel.delay, str(int(channel.lockout)),
                       str(int(channel.priority))))

    def set_search_close_call_settings(self, delay: DelayTime, code_search: bool):
        """
        Sends the set search / close call settings (SCO) command. Requires program mode.

        Args:
            delay: enumeration of the desired delay time
            code_search: whether CTCSS/DCS code search should be enabled
        """
        self._check_ok(self._execute_program_mode_command('SCO', delay.value, str(int(code_search))))

    def set_close_call_settings(self, mode: CloseCallMode, beep: bool, light: bool, bands: List[bool], lockout: bool):
        """
        Sends the set close call settings (CLC) command. Requires program mode.

        Args:
            mode: object representation of the desired close call mode
            beep: whether alert beep should be enabled
            light: whether alert light should be enabled
            bands: list of 5 bools representing which close call bands should be enabled
                (25 - 54, 108 - 137, 137 - 174, 225 - 320, 320 - 512 MHz)
            lockout: whether scan should be unlocked
        """
        assert len(bands) == 5, f'Unexpected bands length of {len(bands)}, expected 5'
        band_str = ''.join([str(int(b)) for b in bands])
        self._check_ok(self._execute_program_mode_command('CLC', mode.value, str(int(beep)), str(int(light)),
                                                          band_str, str(int(lockout))))

    def set_service_search_group(self, states: List[bool]):
        """
        Sends the set service search group (SSG) command. Requires program mode.

        Args:
            states: list of 10 bools representing which of the 10 service groups should have search enabled
                (police, fire/EMS, HAM, marine, railroad, civil air, military air, CB, FRS/GMRS/MURS, racing)
        """
        self._set_program_mode_group('SSG', states)

    def set_weather_priority(self, on: bool):
        """
        Sends the set weather settings (WXS) command. Requires program mode.

        Args:
            on: whether to enable weather priority
        """
        self._set_program_mode_value('WXS', int(on))

    #
    # Combo Commands
    #

    def channel(self, channel: int):
        """Shortcut to jump to a given channel."""
        self.jump_to_channel(channel)

    def update_channel(self, channel: Channel):
        """Sets a given channel's info only if the info has changed."""
        if not BC125AT.compare_channels(self.get_channel_info(channel.index), channel):
            self.set_channel_info(channel)

    def clear_channel(self, index: int):
        """Deletes a given channel if it currently has a name and frequency."""
        channel = self.get_channel_info(index)
        if channel.name or channel.frequency:
            self.delete_channel(index)
