"""Contains classes that are applicable to most if not all known Uniden scanners."""
import abc
import socket
import serial
from enum import Enum
from threading import Thread, Lock
from typing import Optional, Union, Tuple, List
from serial.tools.list_ports import comports


class Modulation(Enum):
    """Enumeration of modulations available to Uniden scanners. Not all scanners support all modulations."""
    AUTO = 'AUTO'
    AM = 'AM'
    FM = 'FM'
    NFM = 'NFM'


class KeyAction(Enum):
    """Enumeration of possible keypad actions."""
    PRESS = 'P'
    LONG_PRESS = 'L'
    HOLD = 'H'
    RELEASE = 'R'


class OperationMode(Enum):
    """Enumeration of operation modes of the scanner."""
    SCAN = 'SCN_MODE'
    SERVICE_SEARCH = 'SVC_MODE'
    CUSTOM_SEARCH = 'CTM_MODE'
    CLOSE_CALL = 'CC_MODE'
    WEATHER = 'WX_MODE'
    TONE_OUT = 'FTO_MODE'


class CommandNotFound(Exception):
    """Exception raised when a command returns an error."""
    pass


class CommandInvalid(Exception):
    """Exception raised when a command used an invalid set of parameters or requires program mode."""
    pass


class UnexpectedResultError(Exception):
    """Exception raised when a command does not return an expected result."""
    pass


class Screen:
    """Representation of the scanner's screen, composed of a list of lines."""

    class Line:
        """Representation of a single line on the scanner's screen."""

        def __init__(self, text: str, formatting: str, large: bool):
            self.text = text
            self.formatting = formatting
            self.large = large

        def __str__(self) -> str:
            """Apply formatting on the line's string."""
            text = self.text

            # underline characters instead of inverting the colors
            underline = False
            for i, c in enumerate(self.formatting):
                if c == '*' and not underline:
                    text = text[:i] + '\033[4m' + text[i:]
                    underline = True
                elif c != '*' and underline:
                    text = text[:i+1] + '\033[0m' + text[i+1:]
                    underline = False

            if underline:
                text += '\033[0m'

            return text

    def __init__(self, *args):
        """
        Constructor, designed to directly take the response to the STS command. Uses the first argument to determine the
        number of lines to produce, then the following pairs are each line and its formatting.
        """
        self.lines = [Screen.Line(args[1 + i * 2], args[2 + i * 2], bool(int(c))) for i, c in enumerate(args[0])]

    def __str__(self) -> str:
        """Join each line's string as a new line."""
        return '\n'.join([str(l) for l in self.lines])


class RadioState:
    """Object representation of radio state returned by both GLG and CIN commands."""

    def __init__(self, index=-1, name='', frequency=0, modulation=Modulation.NFM, tone_code=0):
        """
        Args:
            index: channel number (1 - 500)
            name: name of the selected channel, may be blank, must be <= 16 characters
            frequency: channel frequency in Hz
            modulation: modulation type
            tone_code: optional CTCSS/DCS code identifier, see TONE_MAP values
        """
        self.index = index
        self.name = name
        self.frequency = frequency
        self.modulation = modulation
        self.tone_code = tone_code

    def __str__(self) -> str:
        return f'{self.index}: "{self.name}" {self.frequency / 1e6} MHz {self.modulation.value} {self.tone_code}'


class Channel(RadioState):
    """Object representation of radio state used with CIN command."""

    def __init__(self, index=-1, name='', frequency=0, modulation=Modulation.NFM, tone_code=0, delay='TWO',
                 lockout=True, priority=False):
        """
        Args:
            index: channel number (1-500)
            name: name of the selected channel, may be blank, must be <= 16 characters
            frequency: channel frequency in Hz
            modulation: modulation type
            tone_code: optional CTCSS/DCS code identifier, see TONE_MAP values
            delay: optional delay, default TWO
            lockout: optional channel lockout (removal from scan), default True
            priority: optional channel priority (one per bank), default False
        """
        super().__init__(index, name, frequency, modulation, tone_code)
        self.index = index
        if isinstance(delay, Enum):
            self.delay = delay.name
        else:
            self.delay = delay
        self.lockout = lockout
        self.priority = priority

    def __str__(self) -> str:
        locked = 'Locked' if self.lockout else 'Unlocked'
        priority = ' Priority' if self.priority else ''
        return f'{super().__str__()} {self.delay}s {locked}{priority}'


class BearcatBase(metaclass=abc.ABCMeta):
    """Base object that represents core functionality and API calls for Uniden Bearcat scanners."""

    ENCODING = 'ascii'
    AD_SCALING_FACTOR = 0
    TOTAL_CHANNELS = 0
    DISPLAY_WIDTH = 0
    FREQUENCY_SCALE = 0
    MIN_FREQUENCY_HZ = 0
    MAX_FREQUENCY_HZ = 0
    BAUD_RATES = [115200, 57600, 38400, 19200, 9600, 4800]
    AVAILABLE_KEYS = []
    TONE_MAP = {
        # modes
        'NONE': 0, 'ALL': 0, 'SEARCH': 127, 'NO_TONE': 240,
        # CTCSS
        67.0: 64, 69.3: 65, 71.9: 66, 74.4: 67, 77.0: 68, 79.7: 69, 82.5: 70, 85.4: 71, 88.5: 72, 91.5: 73, 94.8: 74,
        97.4: 75, 100.0: 76, 103.5: 77, 107.2: 78, 110.9: 79, 114.8: 80, 118.8: 81, 123.0: 82, 127.3: 83, 131.8: 84,
        136.5: 85, 141.3: 86, 146.2: 87, 151.4: 88, 156.7: 89, 159.8: 90, 162.2: 91, 165.5: 92, 167.9: 93, 171.3: 94,
        173.8: 95, 177.3: 96, 179.9: 97, 183.5: 98, 186.2: 99, 189.9: 100, 192.8: 101, 196.6: 102, 199.5: 103,
        203.5: 104, 206.5: 105, 210.7: 106, 218.1: 107, 225.7: 108, 229.1: 109, 233.6: 110, 241.8: 111, 250.3: 112,
        254.1: 113,
        # DCS
        23: 128, 25: 129, 26: 130, 31: 131, 32: 132, 36: 133, 43: 134, 47: 135, 51: 136, 53: 137, 54: 138, 65: 139,
        71: 140, 72: 141, 73: 142, 74: 143, 114: 144, 115: 145, 116: 146, 122: 147, 125: 148, 131: 149, 132: 150,
        134: 151, 143: 152, 145: 153, 152: 154, 155: 155, 156: 156, 162: 157, 165: 158, 172: 159, 174: 160, 205: 161,
        212: 162, 223: 163, 225: 164, 226: 165, 243: 166, 244: 167, 245: 168, 246: 169, 251: 170, 252: 171, 255: 172,
        261: 173, 263: 174, 265: 175, 266: 176, 271: 177, 274: 178, 306: 179, 311: 180, 315: 181, 325: 182, 331: 183,
        332: 184, 343: 185, 346: 186, 351: 187, 356: 188, 364: 189, 365: 190, 371: 191, 411: 192, 412: 193, 413: 194,
        423: 195, 431: 196, 432: 197, 445: 198, 446: 199, 452: 200, 454: 201, 455: 202, 462: 203, 464: 204, 465: 205,
        466: 206, 503: 207, 506: 208, 516: 209, 523: 210, 526: 211, 532: 212, 546: 213, 565: 214, 606: 215, 612: 216,
        624: 217, 627: 218, 631: 219, 632: 220, 654: 221, 662: 222, 664: 223, 703: 224, 712: 225, 723: 226, 731: 227,
        732: 228, 734: 229, 743: 230, 754: 231
    }
    BYTE_MAP = {}

    class DelayTime(Enum):
        """Enumeration of allowed delay times."""
        ZERO = '0'
        TWO = '0'

    def __init__(self, port='127.0.0.1', baud_rate=115200, timeout=0.1):
        """
        Args:
            port: serial port name (/dev/ttyX on Linux, COMX on Windows) or proxy address, default 127.0.0.1:65125
            baud_rate: optional serial port speed in bits per second, default 115200
            timeout: optional serial connection timeout in seconds, default 1/10
        """
        if len(port.split('.')) == 4:
            self._serial = None
            if ':' in port:
                parts = port.split(':')
                address = parts[0]
                port = int(parts[1])
            else:
                address = port
                port = 65125

            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.connect((address, port))
        else:
            self._socket = None
            assert baud_rate in self.BAUD_RATES
            self._serial = serial.Serial(port=port, baudrate=baud_rate, stopbits=serial.STOPBITS_ONE,
                                         bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE, xonxoff=False,
                                         rtscts=False, dsrdtr=False, timeout=timeout)

        self._in_program_mode = False
        self.debug = False
        self._cmd_lock = Lock()

    def listen(self, address='127.0.0.1', port=65125):
        """Creates a server socket for other instances to send their bytes to."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind((address, port))
        s.listen()
        Thread(target=self._server_thread, args=(s,), daemon=True).start()

    def _server_thread(self, s: socket.socket):
        """Thread that accepts all incoming connections to the server socket. Created automatically by listen()."""
        while True:
            client, addr = s.accept()
            Thread(target=self._client_listener, args=(client,), daemon=True).start()

    def _client_listener(self, s: socket.socket):
        """Thread that handles all active client connections. Create automatically by _server_thread()."""
        while True:
            recv_bytes = s.recv(4096)
            if not recv_bytes:
                break

            s.sendall(self._execute_command_raw(recv_bytes))

        s.close()

    #
    # Command Execution Helpers
    #

    def _extend_ascii(self, input_bytes: bytes) -> bytes:
        """Replaces Uniden's extended ASCII characters with ASCII ones."""
        output_bytes = bytes()
        for b in input_bytes:
            if b < 0x80:
                output_bytes += bytes([b])
            else:
                try:
                    output_bytes += self.BYTE_MAP[b]
                except:
                    raise UnexpectedResultError(f'Invalid byte in response, {b}')

        return output_bytes

    def _execute_command_raw(self, command: bytes) -> bytes:
        """Executes a command and returns the response all in bytes."""
        with self._cmd_lock:
            if self._serial:
                self._serial.write(command)
                return self._serial.readline()
            elif self._socket:
                self._socket.sendall(command)
                return self._socket.recv(4096)

    def _execute_command(self, *command: str) -> List[str]:
        """Executes a command and returns the response."""
        # build and send command
        if command[0].upper() == 'CIN':
            cmd_str = ','.join([c.upper() if i != 2 else c for i, c in enumerate(command)]) + '\r'
        else:
            cmd_str = ','.join(command).upper() + '\r'
        cmd_bytes = cmd_str.encode(self.ENCODING)
        res_bytes = self._execute_command_raw(cmd_bytes)
        if self.debug:
            print('[SENT]\t\t', cmd_str)

        # decode command string and parse as comma separated string
        res_str = self._extend_ascii(res_bytes).decode('UTF-8').strip()
        res_parts = res_str.split(',')
        if self.debug:
            print('[RECEIVED]\t', res_str)

        # determine if the command successfully ran
        if res_parts[0] == 'ERR':
            raise CommandNotFound('Scanner did not recognize command')
        elif res_parts[0] != command[0]:
            raise UnexpectedResultError(f'Unrecognized command response, {res_parts[0]}')
        elif len(res_parts) == 1:
            raise UnexpectedResultError('No value returned')
        elif res_parts[1] == 'NG':
            raise CommandInvalid('Scanner did not recognize command at this time')

        # skip command and return result
        return res_parts[1:]

    @staticmethod
    def _check_response(response: List[str], expected_values: int):
        """Used for to check that the correct number of values were returned. Raises an UnexpectedResultError is not."""
        if len(response) != expected_values:
            raise UnexpectedResultError(f'{len(response)} values returned, expected {expected_values}')

    @staticmethod
    def _check_ok(response: List[str]):
        """Used for basic commands to check that OK was returned. Raises an UnexpectedResultError is not OK."""
        BearcatBase._check_response(response, 1)
        if response[0] != 'OK':
            raise UnexpectedResultError(f'Not OK response, "{response[0]}"')

    def _execute_action(self, cmd: str):
        """Executes a specified action (no arguments, no response value)."""
        self._check_ok(self._execute_command(cmd))

    def _get_string(self, cmd: str) -> str:
        """Sends a given command expecting a single value in return."""
        response = self._execute_command(cmd)
        self._check_response(response, 1)
        return response[0]

    def _get_number(self, cmd: str) -> int:
        """Sends a given command expecting a single integer in return."""
        response = self._get_string(cmd)
        return int(response)

    def _set_value(self, cmd: str, value: Union[str, int]):
        """Sends a given command and value as a key-value pair."""
        self._check_ok(self._execute_command(cmd, str(value)))

    def _execute_program_mode_command(self, *command: str) -> List[str]:
        """Executes a command and returns the response for commands that require program mode."""
        already_program = self._in_program_mode
        if not already_program:
            self.enter_program_mode()

        response = self._execute_command(*command)

        if not already_program:
            self.exit_program_mode()

        return response

    def _get_program_mode_string(self, cmd: str) -> str:
        """Sends a given command expecting a single value in return, for commands that require program mode."""
        response = self._execute_program_mode_command(cmd)
        self._check_response(response, 1)
        return response[0]

    def _get_program_mode_number(self, cmd: str) -> int:
        """Sends a given command expecting a single integer in return, for commands that require program mode."""
        response = self._get_program_mode_string(cmd)
        return int(response)

    @staticmethod
    def _parse_program_mode_group(states: str) -> List[bool]:
        return [not bool(int(c)) for c in states]

    def _get_program_mode_group(self, cmd: str) -> List[bool]:
        """
        Sends a given command expecting a string representing a list of booleans in return, for commands that require
        program mode.
        """
        response = self._get_program_mode_string(cmd)
        if len(response) != 10:
            raise UnexpectedResultError(f'{len(response)} values returned, expected 10')

        return self._parse_program_mode_group(response)

    def _set_program_mode_value(self, cmd: str, value: Union[str, int]):
        """Sends a given command and value as a key-value pair for commands that require program mode."""
        self._check_ok(self._execute_program_mode_command(cmd, str(value)))

    @staticmethod
    def _build_program_mode_group(states: List[bool]) -> str:
        return ''.join([str(int(not b)) for b in states])

    def _set_program_mode_group(self, cmd: str, states: List[bool]):
        """Sends a given command and string representing a list of booleans, for commands that require program mode."""
        assert len(states) == 10, f'Unexpected states length of {len(states)}, expected 10'
        self._set_program_mode_value(cmd, self._build_program_mode_group(states))

    #
    # Actions
    #

    def enter_program_mode(self):
        """Sends the enter program mode (PRG) command. Required for many commands. Prevents scanner operation."""
        self._execute_action('PRG')
        self._in_program_mode = True

    def exit_program_mode(self):
        """Sends the exit program mode (EPG) command. Resumes normal scanner operation."""
        self._execute_action('EPG')
        self._in_program_mode = False

    #
    # Getters
    #

    def get_model(self) -> str:
        """
        Sends the get model (MDL) command.

        Returns:
            scanner's model number
        """
        return self._get_string('MDL')

    def get_version(self) -> str:
        """
        Sends the get version (VER) command.

        Returns:
            scanner's firmware version number
        """
        return self._get_string('VER')

    def get_global_lockout_freq(self) -> int:
        """
        Sends the get global lockout freq (GLF) command.

        Returns:
            the next lockout frequency in Hz or -100 when all end of list is reached
        """
        return self._get_number('GLF') * self.FREQUENCY_SCALE

    #
    # Program Mode Getters
    #

    def clear_all_memory(self):
        """Sends the clear all memory (CLR) command. Requires program mode. Factory resets the scanner."""
        self._check_ok(self._execute_program_mode_command('CLR'))

    def get_custom_search_group(self) -> List[bool]:
        """
        Sends the get custom search group (CSG) command. Requires program mode.

        Returns:
            a list of 10 bools representing whether search is enabled for each of the 10 custom groups
        """
        return self._get_program_mode_group('CSG')

    def get_status(self) -> [Screen, bool, bool]:
        pass

    #
    # Setters
    #

    def unlock_global_lo(self, frequency: int):
        """
        Sends the unlock global lo (ULF) command.

        Args:
            frequency: frequency in Hz to unlock globally
        """
        assert self.MIN_FREQUENCY_HZ <= frequency <= self.MAX_FREQUENCY_HZ,\
            f'Unexpected frequency {frequency}, expected 25 - 512 MHz'
        self._set_value('ULF', frequency // self.FREQUENCY_SCALE)

    #
    # Program Mode Setters
    #

    def lock_out_frequency(self, frequency: int):
        """
        Sends the lock out frequency (LOF) command. Requires program mode.

        Args:
            frequency: frequency in Hz to lockout
        """
        assert self.MIN_FREQUENCY_HZ <= frequency <= self.MAX_FREQUENCY_HZ,\
            f'Unexpected frequency {frequency}, expected 25 - 512 MHz'
        self._set_program_mode_value('LOF', frequency // self.FREQUENCY_SCALE)

    def set_custom_search_group(self, states: List[bool]):
        """
        Sends the set custom search group (CSG) command. Requires program mode.

        Args:
            states: list of 10 bools representing which of the 10 custom groups should have search enabled
        """
        self._set_program_mode_group('CSG', states)


class BearcatCommon(BearcatBase, metaclass=abc.ABCMeta):
    """Object that represents API calls available to nearly all Uniden Bearcat scanners."""

    #
    # Getters
    #

    def get_volume(self) -> int:
        """
        Sends the get volume (VOL) command.

        Returns:
            volume level, 0 - 15
        """
        return self._get_number('VOL')

    def get_squelch(self) -> int:
        """
        Sends the get squelch (SQL) command.

        Returns:
            squelch level, 0 - 15
        """
        return self._get_number('SQL')

    def get_window_voltage(self) -> Tuple[float, float]:
        """
        Sends the get window voltage (WIN) command. This is an unofficial command for many scanners.

        Returns:
            window potential as a percent of the A/D value, 0 - 1
            window frequency in Hz
        """
        response = self._execute_command('WIN')
        self._check_response(response, 2)
        # TODO: determine scaling factor of voltage A/D and return voltage
        return int(response[0]) / self.AD_SCALING_FACTOR, int(response[1]) * self.FREQUENCY_SCALE

    #
    # Setters
    #

    def set_volume(self, level: int):
        """
        Sends the set volume (VOL) command.

        Args:
            level: volume level, 0 - 15
        """
        assert 0 <= level <= 15, f'Unexpected volume level {level}, expected 0 - 15'
        self._set_value('VOL', level)

    def set_squelch(self, level: int):
        """
        Sends the set squelch (SQL) command.

        Args:
            level: volume level, 0 - 15
        """
        assert 0 <= level <= 15, f'Unexpected squelch level {level}, expected 0 - 15'
        self._set_value('SQL', level)

    #
    # Program Mode Setters
    #

    def delete_channel(self, channel: int):
        """
        Sends the delete channel (DCH) command. Requires program mode.

        Args:
            channel: channel number to delete
        """
        assert 1 <= channel <= self.TOTAL_CHANNELS
        self._set_program_mode_value('DCH', channel)

    #
    # Key Pushers
    #

    def _key_action(self, key: str, action: KeyAction):
        """
        Sends the key (KEY) command. This is an unofficial command for many scanners.

        Args:
            key: desired key to press
            action: enumeration of the desired action to perform on the given key
        """
        key = key.upper()
        assert len(key) == 1, 'Key must be a single character'
        assert key in self.AVAILABLE_KEYS, f'Unrecognized key, {key}'
        self._check_ok(self._execute_command('KEY', key, action.value))

    def press_key(self, key: str):
        """
        Simulates a key press.

        Args:
            key: desired key to press
        """
        self._key_action(key, KeyAction.PRESS)

    def press_key_sequence(self, keys: str):
        """
        Simulates a sequence of key presses.

        Args:
            keys: desired keys to press in sequence
        """
        for k in keys:
            self.press_key(k)

    def long_press_key(self, key: str):
        """
        Simulates a long key press.

        Args:
            key: desired key to long press
        """
        self._key_action(key, KeyAction.LONG_PRESS)

    def hold_key(self, key: str):
        """
        Simulates a held key.

        Args:
            key: desired key to hold
        """
        self._key_action(key, KeyAction.HOLD)

    def release_key(self, key: str):
        """
        Simulates a released key.

        Args:
            key: desired key to release
        """
        self._key_action(key, KeyAction.RELEASE)


class BearcatCommonContrast(BearcatCommon, metaclass=abc.ABCMeta):
    """Object that extends BearcatCommon to add contrast which is available to nearly all scanners."""

    #
    # Program Mode Getters
    #

    def get_contrast(self) -> str:
        """
        Sends the get contrast (CNT) command. Requires program mode.

        Returns:
            display contrast level, 0 - 15
        """
        return self._get_program_mode_string('CNT')

    #
    # Program Mode Setters
    #

    def set_contrast(self, level: int):
        """
        Sends the set contrast (CNT) command. Requires program mode.

        Args:
            level: desired contrast level, 0 - 15
        """
        assert 0 <= level <= 15, f'Unexpected contrast level {level}, expected 0 - 15'
        self._set_program_mode_value('CNT', level)


def find_scanners() -> List[BearcatBase]:
    """Scans serial ports for connected scanners."""
    scanners = []
    ports = [p.device for p in comports() if p.description != 'n/a']
    for port in ports:
        scanner = detect_scanner(port)
        if scanner:
            scanners.append(scanner)

    return scanners

def detect_scanner(port: str) -> Optional[BearcatBase]:
    """Detects a scanner on a given serial port (or IP address)."""
    for rate in BearcatBase.BAUD_RATES:
        try:
            # attempt to connect to the scanner
            bc = BearcatBase(port, rate)
            try:
                model = bc.get_model()
            except CommandNotFound:
                # command not found probably means there is garbage in the buffer, try again
                model = bc.get_model()

            version = bc.get_version()
        except serial.SerialException as e:
            if e.errno == 13:
                print('Insignificant permissions for', port)

            break
        except UnexpectedResultError:
            continue

        # construct an object based on the discovered scanner
        scanner = construct_scanner(model, port, rate)
        if scanner:
            print(f'Found {model} ({version}): {port} @ {rate}')
            return scanner


def construct_scanner(model, port, rate=115200):
    """Constructs a scanner object based on the given model."""
    if model == 'BC125AT':
        from bearcat.handheld.bc125at import BC125AT
        return BC125AT(port, rate)
    elif model == 'BC75XLT':
        from bearcat.handheld.bc75xlt import BC75XLT
        return BC75XLT(port, rate)
