"""Contains classes that are applicable to most if not all known handheld Uniden scanners."""
import abc
from enum import Enum
from typing import List, Tuple

from bearcat import BearcatBase, UnexpectedResultError, OperationMode


class BearcatHandheld(BearcatBase, metaclass=abc.ABCMeta):
    """Object that represents API calls available to all handheld Uniden Bearcat scanners."""

    #
    # Actions
    #

    def power_off(self):
        """Sends the power off (POF) command. This is an unofficial command for many scanners."""
        self._execute_action('POF')

    #
    # Getters
    #

    def get_battery_voltage(self) -> float:
        """
        Sends the get battery voltage (BAV) command. This is an unofficial command for many scanners.

        Returns:
            battery potential in volts
        """
        return self._get_number('BAV') * 6.4 / 1023


class BasicHandheld(BearcatHandheld, metaclass=abc.ABCMeta):
    """Object that represents API calls available to both the BC125AT and BC75XLT."""

    AD_SCALING_FACTOR = 255
    FREQUENCY_SCALE = 100
    MIN_FREQUENCY_HZ = int(25e6)
    MAX_FREQUENCY_HZ = int(512e6)
    AVAILABLE_KEYS = [
        '<', '^', '>',
        'H', '1', '2', '3',
        'S', '4', '5', '6',
        'R', '7', '8', '9',
        'L', 'E', '0', '.',
        'P', 'F'
    ]

    class OperationMode(Enum):
        pass

    class PriorityMode(Enum):
        """Enumeration of priority modes supported by these scanners."""
        OFF = '0'
        ON = '1'
        PLUS = '2'
        DND = '3'

    class TestMode(Enum):
        pass

    #
    # Getters
    #

    def memory_read(self, location: int) -> Tuple[List[int], int]:
        """
        Sends the memory read (MRD) command. This appears to be an unofficial and undocumented command for all
        scanners. There is a corresponding memory write (MWR) command that I am too afraid to investigate right now.

        Args:
            32-bit value, likely register number

        Returns:
            16 bytes likely starting at the given memory location
            32-bit value
        """
        assert 0 <= location <= 0xFFFFFFFF
        response = self._execute_command('MRD', str(location))
        self._check_response(response, 18)
        assert int(response[0], 16) == location
        return [int(b, 16) for b in response[1:17]], int(response[17], 16)

    #
    # Setters
    #

    def jump_mode(self, mode: OperationMode):
        """Jump mode (JPM) command. This is an unofficial command for these scanners."""
        self._set_value('JPM', mode.value)

    #
    # Program Mode Getters
    #

    def get_band_plan(self) -> bool:
        """
        Sends the get band plan (BPL) command. Requires program mode.

        Returns:
            whether the Canadian (True) or American (False) band plan is selected
        """
        return bool(self._get_program_mode_number('BPL'))

    def get_custom_search_settings(self, group: int) -> Tuple[int, int, int]:
        """
        Sends the get custom search settings (CSP) command. Requires program mode.

        Returns:
            search group number, 1 - 10
            search upper limit in Hz
            search lower limit in Hz
        """
        assert 1 <= group <= 10
        response = self._execute_program_mode_command('CSP', str(group))
        self._check_response(response, 3)
        return int(response[0]), int(response[1]) * self.FREQUENCY_SCALE, int(response[2]) * self.FREQUENCY_SCALE

    def get_priority_mode(self) -> PriorityMode:
        """
        Sends the get priority mode (PRI) command. Requires program mode.

        Returns:
            priority mode as an enumeration
        """
        return BasicHandheld.PriorityMode(self._get_program_mode_number('PRI'))

    def get_scan_channel_group(self) -> List[bool]:
        """
        Sends the get scan channel group (SCG) command. Requires program mode.

        Returns:
            a list of 10 bools representing whether scanning is enabled for each of the 10 channel groups
        """
        return self._get_program_mode_group('SCG')

    #
    # Program Mode Setters
    #

    def set_band_plan(self, canada: bool):
        """
        Sends the set band plan (BPL) command. Requires program mode.

        Args:
            canada: whether Canadian (True) or American (False) band plan should be used
        """
        self._set_program_mode_value('BPL', int(canada))

    def set_custom_search_settings(self, index: int, lower_limit: int, upper_limit: int):
        """
        Sends the set custom search settings (CSP) command. Requires program mode.

        Args:
            index: custom search number
            lower_limit: desired custom search lower frequency limit in Hz
            upper_limit: desired custom search upper frequency limit in Hz
        """
        assert 1 <= index <= 10, f'Unexpected search index {index}, expected 1 - 10'
        assert BasicHandheld.MIN_FREQUENCY_HZ <= lower_limit <= BasicHandheld.MAX_FREQUENCY_HZ,\
            f'Unexpected lower limit {lower_limit}, expected 25 - 512 MHz'
        assert BasicHandheld.MIN_FREQUENCY_HZ <= upper_limit <= BasicHandheld.MAX_FREQUENCY_HZ,\
            f'Unexpected upper limit {upper_limit}, expected 25 - 512 MHz'
        self._check_ok(self._execute_program_mode_command('CSP', str(index),
                                                          str(lower_limit // BasicHandheld.FREQUENCY_SCALE),
                                                          str(upper_limit // BasicHandheld.FREQUENCY_SCALE)))

    def set_priority_mode(self, mode: PriorityMode):
        """
        Sends the set priority mode (PRI) command. Requires program mode.

        Args:
            mode: enumeration of the desired priority
        """
        self._set_program_mode_value('PRI', mode.value)

    def go_to_quick_search_hold_mode(self, frequency: int, delay=''):
        """
        Go to quick search hold mode (QSH) command. This is an unofficial command for these scanners.

        Args:
            frequency: channel frequency in Hz
            delay: optional delay, default TWO
        """
        if not isinstance(delay, self.DelayTime):
            delay = self.DelayTime.TWO

        assert self.MIN_FREQUENCY_HZ <= frequency <= self.MAX_FREQUENCY_HZ,\
            f'Unexpected frequency {frequency}, expected {self.MIN_FREQUENCY_HZ} - {self.MAX_FREQUENCY_HZ}'
        self._check_ok(self._execute_command('QSH', str(int(frequency / self.FREQUENCY_SCALE)), '', '', '', '',
                                             delay.name, '', '', '', '', '', '', ''))

    def set_scan_channel_group(self, states: List[bool]):
        """
        Sends the set scan channel group (SCG) command. Requires program mode.

        Args:
            states: list of 10 bools representing which of the 10 channel groups should have scanning enabled
        """
        self._set_program_mode_group('SCG', states)

    def enter_test_mode(self, mode: TestMode):
        """Enter test mode (TST) command. This appears to be an unofficial and undocumented command for all scanners."""
        assert self._in_program_mode, 'Scanner must be manually put into program mode to use test mode'
        try:
            self._execute_command('TST', mode.value, 'UNIDEN_TEST_MODE')
        except UnexpectedResultError:
            pass
        self._in_program_mode = False

    #
    # Combo Commands
    #

    def scan_groups(self, *groups: int):
        """Applies a set of scan channel groups and switches to scan mode."""
        band_selection = [i + 1 not in groups for i in range(10)]
        self.set_scan_channel_group(band_selection)
        self.jump_mode(OperationMode.SCAN)

    def frequency(self, frequency_mhz: float):
        """Shortcut to jump to a given frequency."""
        self.go_to_quick_search_hold_mode(frequency=int(frequency_mhz * 1e6))

    def print_screen(self):
        """Fetches and prints the current screen state."""
        screen, _, _ = self.get_status()
        print(screen)
