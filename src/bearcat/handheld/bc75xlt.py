"""Contains the class represention of the Uniden BC75XLT scanner."""
from enum import Enum
from typing import Tuple, List

from bearcat import Modulation, UnexpectedResultError, Screen, RadioState, Channel, BearcatCommon
from bearcat.handheld import BasicHandheld


class BC75XLT(BearcatCommon, BasicHandheld):
    """
    Object for interacting with the Uniden BC75XLT serial API. All official and many known unofficial calls are
    supported. See https://info.uniden.com/twiki/pub/UnidenMan4/BC75XLT/BC75XLT_Protocol.pdf for official API.
    """

    AD_SCALING_FACTOR = 255
    TOTAL_CHANNELS = 300
    DISPLAY_WIDTH = 14
    BAUD_RATES = [57600]
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

    class CloseCallMode(Enum):
        """Enumeration of close call modes supported by the BC75XLT."""
        OFF = '0'
        PRIORITY = '1'
        DND = '2'

    class DelayTime(Enum):
        """Enumeration of allowed delay times."""
        ZERO = '0'
        TWO = '1'

    class TestMode(Enum):
        """Enumeration of various hardware test modes available on the BC75XLT."""
        SOFTWARE = '1'
        CLOSE_CALL = '2'
        KEYPAD = '4'
        DISPLAY = '5'

    def __init__(self, port='127.0.0.1', baud_rate=57600, timeout=0.1):
        super().__init__(port, baud_rate, timeout)

    @staticmethod
    def compare_channels(a: Channel, b: Channel) -> bool:
        return a.frequency == b.frequency and a.delay == b.delay and a.lockout == b.lockout and a.priority == b.priority

    @staticmethod
    def determine_modulation(frequency_hz):
        if frequency_hz < 28e6 or 108 <= frequency_hz < 137:
            return Modulation.AM
        else:
            return Modulation.NFM

    #
    # Getters
    #

    def get_power(self) -> Tuple[float, float]:
        """
        Sends the get power (PWR) command. This is an unofficial command for the BC75XLT.

        Returns:
            received power on a scale of 0 to 1
            frequency in Hz
        """
        response = self._execute_command('PWR')
        self._check_response(response, 2)
        # TODO: convert to RSSI
        return int(response[0]) / 512, int(response[1]) * self.FREQUENCY_SCALE

    def get_status(self) -> Tuple[Screen, bool, bool]:
        """
        Sends the get status (STS) command. This is an unofficial command for the BC75XLT.

        Returns:
            object representation of the scanner's screen
            whether the scanner is squelched
            whether the scanner is muted.
        """
        response = self._execute_command('STS')
        return Screen(*response[:-2]), bool(int(response[-2])), bool(int(response[-1]))

    def get_reception_status(self) -> Tuple[RadioState, bool, bool]:
        """
        Sends the get reception status (GLG) command. This is an unofficial command for the BC75XLT.

        Returns:
            object representation of the scanner's radio state
            whether the scanner is squelched
            whether the scanner is muted.
        """
        response = self._execute_command('GLG')
        self._check_response(response, 12)
        state = RadioState(int(float(response[0]) * 1e6), Modulation(response[1]))
        return state, bool(int(response[7])), bool(int(response[8]))

    #
    # Program Mode Getters
    #

    def get_key_beep(self) -> bool:
        """
        Sends the get key beep (KBP) command. Requires program mode.

        Returns:
            whether the keypad is locked
        """
        # BC75XLT doesn't use first arg
        response = self._execute_program_mode_command('KBP')
        self._check_response(response, 2)
        return bool(int(response[1]))

    def get_channel_info(self, channel: int) -> Channel:
        """
        Sends the get channel info (CIN) command. Requires program mode.

        Args:
            channel: the channel number to investigate, 1 - 500

        Returns:
            object representation of the channel configuration
        """
        # BC75XLT skips modulation and tone code
        assert 1 <= channel <= BC75XLT.TOTAL_CHANNELS
        response = self._execute_program_mode_command('CIN', str(channel))
        self._check_response(response, 8)
        frequency_hz = int(response[2]) * BC75XLT.FREQUENCY_SCALE
        return Channel(int(response[0]), response[1], frequency_hz, BC75XLT.determine_modulation(frequency_hz), 0,
                       BC75XLT.DelayTime(response[5]), bool(int(response[6])), bool(int(response[7])))

    def get_custom_search_group(self) -> Tuple[List[bool], DelayTime, bool]:
        """
        Sends the get custom search group (CSG) command. Requires program mode.

        Returns:
            a list of 10 bools representing whether search is enabled for each of the 10 custom groups
            delay time as an enumeration
            whether the direction is down or up
        """
        response = self._execute_program_mode_command('CSG')
        self._check_response(response, 3)

        if len(response[0]) != 10:
            raise UnexpectedResultError(f'{len(response)} values returned, expected 10')

        print(response[0])
        return self._parse_program_mode_group(response[0]), BC75XLT.DelayTime(response[1]), bool(int(response[2]))

    def get_search_close_call_settings(self) -> Tuple[DelayTime, bool]:
        """
        Sends the get search / close call settings (SCO) command. Requires program mode.

        Returns:
            delay time as an enumeration
            whether the direction is down or up
        """
        response = self._execute_program_mode_command('SCO')
        self._check_response(response, 3)
        return BC75XLT.DelayTime(response[0]), bool(int(response[2]))

    def get_close_call_settings(self) -> Tuple[CloseCallMode, bool, bool, List[bool]]:
        """
        Sends the get close call settings (CLC) command. Requires program mode.

        Returns:
            close call mode as an enumeration
            whether the alert beep is enabled
            whether the alert light is enabled
            a list of 5 bools representing whether each of the 5 close call bands are enabled
        """
        # BC75XLT missing lockout
        response = self._execute_program_mode_command('CLC')
        self._check_response(response, 5)
        return BC75XLT.CloseCallMode(response[0]), bool(int(response[1])), bool(int(response[2])),\
            self._parse_program_mode_group(response[3])

    #
    # Program Mode Setters
    #

    def set_key_beep(self, lock: bool):
        """
        Sends the set key beep (KBP) command. Requires program mode.

        Args:
            lock: whether keypad lock should be enabled
        """
        self._check_ok(self._execute_program_mode_command('KBP', '', str(int(lock))))

    def set_channel_info(self, channel: Channel):
        """
        Sends the set channel info (CIN) command. Requires program mode.

        Args:
            channel: object representation of the desired channel parameters
        """
        self._check_ok(self._execute_program_mode_command('CIN', str(channel.index), '',
                                                          str(int(channel.frequency / BC75XLT.FREQUENCY_SCALE)), '', '',
                                                          channel.delay, str(int(channel.lockout)),
                                                          str(int(channel.priority))))

    def set_custom_search_group(self, states: List[bool], delay: DelayTime, direction_down: bool):
        """
        Sends the set custom search group (CSG) command. Requires program mode.

        Args:
            states: list of 10 bools representing which of the 10 custom groups should have search enabled
            delay: enumeration of the desired delay time
            direction_down: whether the direction is down or up
        """
        assert len(states) == 10, f'Unexpected states length of {len(states)}, expected 10'
        state_str = self._build_program_mode_group(states)
        self._check_ok(self._execute_program_mode_command('CSG', state_str, delay.value, str(int(direction_down))))

    def set_search_close_call_settings(self, delay: DelayTime, direction_down: bool):
        """
        Sends the set search / close call settings (SCO) command. Requires program mode.

        Args:
            delay: enumeration of the desired delay time
            direction_down: whether the direction is down or up
        """
        self._check_ok(self._execute_program_mode_command('SCO', delay.value, '', str(int(direction_down))))

    def set_close_call_settings(self, mode: CloseCallMode, beep: bool, light: bool, bands: List[bool]):
        """
        Sends the set close call settings (CLC) command. Requires program mode.

        Args:
            mode: object representation of the desired close call mode
            beep: whether alert beep should be enabled
            light: whether alert light should be enabled
            bands: list of 5 bools representing which close call bands should be enabled
                (25 - 54, 108 - 137, 137 - 174, 225 - 320, 320 - 512 MHz)
        """
        assert len(bands) == 5, f'Unexpected bands length of {len(bands)}, expected 5'
        band_str = ''.join([str(int(b)) for b in bands])
        self._check_ok(self._execute_program_mode_command('CLC', mode.value, str(int(beep)), str(int(light)), band_str, ''))

    #
    # Combo Commands
    #

    def channel(self, channel: int):
        """Shortcut to jump to a given channel."""
        self.go_to_quick_search_hold_mode(25000000)
        self.press_key_sequence(f'{channel}H')

    def update_channel(self, channel: Channel):
        """Sets a given channel's info only if the info has changed."""
        if not BC75XLT.compare_channels(self.get_channel_info(channel.index), channel):
            self.set_channel_info(channel)

    def clear_channel(self, index: int):
        """Deletes a given channel if it currently has a frequency."""
        channel = self.get_channel_info(index)
        if channel.frequency:
            modulation = BC75XLT.determine_modulation(channel.frequency)
            self.set_channel_info(Channel(channel.index, '', 0, modulation, 0, BC75XLT.DelayTime.TWO, True, False))
