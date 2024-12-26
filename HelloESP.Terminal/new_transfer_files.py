import time
import os
from typing import Optional, Tuple, List
import serial
import hashlib
from threading import Thread
from queue import Queue
import re

from generalFunctions import contains_alphanumeric, safe_decode, print_err

MAX_FILENAME_LENGTH = 255
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB

DEBUG_ON_TERMINAL = True

###
###
###


class SerialCommandError(Exception):
    """Custom exception for serial command errors"""
    pass


class FileValidationError(Exception):
    """Custom exception for file validation errors"""
    pass


def validate_filename(filename: str) -> None:
    """
    Validate filename before sending to device.

    Args:
        filename: Name of file to validate

    Raises:
        FileValidationError: If filename is invalid
    """
    if not filename or len(filename) > MAX_FILENAME_LENGTH:
        raise FileValidationError(f"Filename too long (max {MAX_FILENAME_LENGTH} chars)")

    invalid_chars = set('\\/:*?"<>|')
    if any(c in invalid_chars for c in filename):
        raise FileValidationError("Filename contains invalid characters")

    if filename.startswith('.') or filename.startswith(' '):
        raise FileValidationError("Filename cannot start with dot or space")


def parse_esp32_log(line: str) -> dict:
    """
    Analizza una linea di log ESP32 e separa il timestamp, il tag e il messaggio.

    Args:
        line (str): La linea di log da analizzare, es. 'I (739418) HELLOESP: wait'

    Returns:
        dict: Dizionario contenente level, timestamp, tag e message.
              Ritorna None se la linea non corrisponde al formato atteso.
    """
    import re

    # Pattern per riconoscere il formato: Level (timestamp) TAG: message
    pattern = r'^([A-Z])\s*\((\d+)\)\s*([^:]+):\s*(.*)$'

    match = re.match(pattern, line)
    if match:
        level, timestamp, tag, message = match.groups()
        return {
            'level': level,
            'timestamp': int(timestamp),
            'tag': tag.strip(),
            'message': message.strip()
        }
    return None


###
###
###

class SerialCommandHandler:
    def __init__(self, serial_interface):
        self.serial_interface = serial_interface
        self.wait_for_response_in_use = False
        self.wfr_thisLine = ""

    def parse_esp32_log(self, line: str) -> dict:
        """
        Analizza una linea di log ESP32 e separa il timestamp, il tag e il messaggio.
        """
        pattern = r'^([A-Z])\s*\((\d+)\)\s*([^:]+):\s*(.*)$'
        match = re.match(pattern, line)
        if match:
            level, timestamp, tag, message = match.groups()
            return {
                'level': level,
                'timestamp': int(timestamp),
                'tag': tag.strip(),
                'message': message.strip()
            }
        return None

    def wait_for_response(self, timeout: float = 5, waitEnd=False) -> Tuple[bool, str]:
        while self.wait_for_response_in_use:
            print("wait_for_response in use elsewhere")
            time.sleep(0.1)

        self.wait_for_response_in_use = True

        result_queue = Queue()
        # thisLine = ""
        goOn_read = True

        stream_handler = self.serial_interface.stream_handler
        orig_stream_handler_cbk = stream_handler.default_callback

        if not self.serial_interface.block_serial:
            self.serial_interface.redirect_serial = True

        def done():
            nonlocal stream_handler
            nonlocal orig_stream_handler_cbk
            # global wfr_thisLine

            # if wfr_thisLine:
            #    ser.main_thread_queue.put(("self.append_terminal", wfr_thisLine))
            #    wfr_thisLine = ''

            self.wait_for_response_in_use = False

            if not self.serial_interface.block_serial:
                self.serial_interface.redirect_serial = False

            stream_handler.default_callback = orig_stream_handler_cbk

        res = [] if waitEnd else None

        def on_received_normal(line):
            nonlocal goOn_read
            nonlocal result_queue
            nonlocal res

            #print("wait_for_response on_received_normal (", len(line), ") bytes")

            self.wfr_thisLine += line

            while len(self.wfr_thisLine) > 0:
                spl = self.wfr_thisLine.split('\n')
                line = spl[0]

                print("wait_for_response processing line: ", line)

                if len(spl) > 1:
                    self.wfr_thisLine = '\n'.join(spl[1:])
                else:
                    self.wfr_thisLine = ""

                if not contains_alphanumeric(line):
                    continue

                print("wait_for_response line: ", line)

                esp_tag = parse_esp32_log(line)

                # Handle different log levels while continuing to wait for actual response
                if esp_tag is not None:
                    line = esp_tag['message']
                elif line.startswith('\x1b'):
                    try:
                        log_level, message = line.split(":", 1)
                        print(f"[{log_level}] {message.strip()}")
                        # line = message.strip()
                    except Exception as e:
                        print("Received void")

                if esp_tag:
                    print(f"[{esp_tag['level']}] {esp_tag['message']}")
                else:
                    print(line)

                # move in global const
                ok = '!!OK!!:'
                error = '!!ERROR!!:'

                # Process actual responses
                if ok in line:
                    spl = ('🤷'+line).split(ok)
                    #lines = spl[1].split('\n')
                    #line = '\n'.join(lines[1:]) if len(lines) > 0 else ''
                    #if line:
                    #    self.wfr_thisLine += line + '\n'

                    line = spl[1]
                    if waitEnd:
                        if '!!END!!' in line:
                            result_queue.put(("res", [True, res]))
                            break
                        else:
                            res.append(line)
                    else:
                        res = [True, line]
                        break
                elif error in line:
                    spl = ('🤷'+line).split(error)
                    #lines = spl[1].split('\n')
                    #line = '\n'.join(lines[1:]) if len(lines) > 0 else ''
                    #if line:
                    #    self.wfr_thisLine += line + '\n'

                    res = [False, spl[1]]

                    if waitEnd:
                        result_queue.put(("res", res))
                    break
                else:
                    if line:
                        print("self.append_terminal: ", line)
                        self.serial_interface.main_thread_queue.put(("self.append_terminal", line + '\n'))

                if not waitEnd:
                    if res is not None:
                        goOn_read = False
                        self.serial_interface.main_thread_queue.put(("self.append_terminal", self.wfr_thisLine + '\n'))

            if not waitEnd:
                if res is not None:
                    result_queue.put(("res", res))
            else:
                if self.wfr_thisLine and False:
                    self.serial_interface.main_thread_queue.put(("self.append_terminal", self.wfr_thisLine + '\n'))

        on_received_normal("\n")
        stream_handler.default_callback = on_received_normal

        def process_serial_data(ser, stream_handler, start_time, result_queue):
            nonlocal goOn_read

            try:
                ifData = ser.serial_conn.in_waiting if ser.block_serial else ser.last_serial_output is not None
                if ifData and goOn_read:

                    data = None
                    try:
                        if ser.block_serial:
                            # ser.serial_conn.flush()
                            data = ser.serial_conn.read(ser.serial_conn.in_waiting)
                        else:
                            data = ser.last_serial_output
                            ser.last_serial_output = None

                        # print("wait_for_response: serial read data: ", data)

                        text = ''

                        if data is not None:
                            try:
                                text = data.decode('utf8')
                            except:
                                text = safe_decode(data)

                        if not contains_alphanumeric(text):
                            text = ''

                        if len(text) > 0:
                            result_queue.put(("process", text))
                            print("(received ", len(data), "bytes)")

                        # result_queue.put(("start_time", time.time()))

                    except Exception as e:
                        print("wait_for_response exception: ", data)
                        result_queue.put(("exception", e))
            except Exception as e:
                result_queue.put(("exception", e))

        # timeout = -1
        stream_handler.exit_context()
        start_time = time.time()
        while (time.time() - start_time) < timeout or timeout == -1:
            if goOn_read:
                # Esegui il corpo del while in un thread
                thread = Thread(target=process_serial_data,
                                args=(self.serial_interface, stream_handler, start_time, result_queue))
                thread.start()
                thread.join()  # Aspetta che il thread finisca

            # Controlla i risultati dal thread
            while not result_queue.empty():
                msg_type, value = result_queue.get()
                if msg_type == "exception":
                    print("process_serial_data exception: ", str(value))
                    # raise value
                elif msg_type == "start_time":
                    print("update start_time: ", value)
                    # start_time = value
                elif msg_type == "res":
                    done()
                    print("end receive result: ", value)
                    if DEBUG_ON_TERMINAL:
                        self.serial_interface.main_thread_queue.put(("self.append_terminal", "wait_for_response: " + str(value)))
                    return value[0], value[1]
                elif msg_type == "process":
                    print("processing ", len(value), " bytes: ", value)
                    stream_handler.process_string(value)

            time.sleep(0.1)

            if not self.wait_for_response_in_use:
                break

        done()
        print("forced end receive")
        return False, "Timeout receive cycle"

    ###
    ###
    ###

    def send_buffer(self, buffer, ping=True):
        serInt = self.serial_interface
        ser = serInt.serial_conn

        if ping:
            ser.write("$$$PING$$$\n".encode('utf8'))
            ser.flush()
            success, msg = self.wait_for_response()

            if not success:
                print("Ping unsuccessful: " + msg)
            else:
                print("PONG!")

        if type(buffer) is str:
            buffer = buffer.encode('utf8')

        ser.write(buffer)
        ser.flush()

    ###
    ###
    ###

    def cmd_start(self):
        ser = self.serial_interface

        print("CMD: SILENCE_ON")
        ser.block_serial = True
        ser.serial_conn.write("$$$SILENCE_ON$$$\n".encode())
        time.sleep(0.1)

    def cmd_end(self):
        ser = self.serial_interface

        print("CMD: SILENCE_OFF")
        ser.serial_conn.write("$$$SILENCE_OFF$$$\n".encode())
        time.sleep(0.1)

        if ser.block_serial:
            ser.block_serial = False

    ###
    ###
    ###

    def write_file(self, filename: str, data: bytes) -> Tuple[bool, str]:
        """Write data to device with chunk verification."""

        self.cmd_start()

        ser = self.serial_interface.serial_conn

        try:
            validate_filename(filename)
            if not self.validate_file_size(data):
                return False, f"Invalid file size (max {MAX_FILE_SIZE} bytes)"

            file_hash = hashlib.md5(data).hexdigest()
            if not self.check_existing_file(filename, len(data)):
                return False, "File exists with same size"

            # Inizia trasferimento
            success, response = self.send_write_command(filename, len(data), file_hash)
            if not success:
                return False, "Not ready for write: " + response

            '''
            success, status = wait_for_response(ser)
            if not success:
                return False, "Not ready for chunks: " + status

            serInterface.append_terminal("Ready for chunks: " + status)
            '''

            # Suddividi in chunk e verifica
            chunk_size = 1024
            total_chunks = (len(data) + chunk_size - 1) // chunk_size

            for chunk_num in range(total_chunks):
                print("Writing chunk n " + str(chunk_num))
                start = chunk_num * chunk_size
                end = min(start + chunk_size, len(data))
                chunk = data[start:end]

                # Calcola hash del chunk
                chunk_hash = hashlib.md5(chunk).hexdigest()

                # Invia dimensione chunk e hash
                command = f"$$$CHUNK$$${len(chunk)},{chunk_hash}\n"
                self.send_buffer(command, ping=False)

                success, message = self.wait_for_response()
                if not success:
                    return False, f"Chunk prep failed: {message}"

                print("Ready for chunk: ", message)

                # Invia chunk
                ser.write(chunk)
                ser.flush()

                # Verifica ricezione
                success, message = self.wait_for_response()
                if not success:
                    return False, f"Chunk verification failed: {message}"
                else:
                    print("Chunk sent: ", message)

            # Verifica finale
            command = "$$$VERIFY_FILE$$$\n"
            self.send_buffer(command.encode('utf8'))

            resp = self.wait_for_response()
            self.cmd_end()
            return resp

        except Exception as e:
            self.cmd_end()
            print_err("Transfer error: ", e)
            return False, f"Transfer error: {str(e)}"

    def validate_file_size(self, data: bytes) -> bool:
        """Validate file size constraints."""
        return 0 < len(data) <= MAX_FILE_SIZE

    def check_existing_file(self, filename: str, size: int) -> bool:
        """Check if file exists with same size."""

        self.cmd_start()

        command = f"$$$CHECK_FILE$$${filename}\n"
        self.send_buffer(command)

        success, message = self.wait_for_response()

        self.cmd_end()

        if success:
            try:
                existing_size = int(message.split(':')[0])
                return existing_size != size
            except ValueError:
                return True
        return True

    def send_write_command(self, filename: str, size: int, file_hash: str):
        """Send initial write command."""
        command = f"$$$WRITE_FILE$$${filename},{size},{file_hash}\n"
        print("sending write command: ", command)
        self.send_buffer(command)

        success, message = self.wait_for_response()
        return success, message

    def read_file(self, filename: str) -> bytes:
        """
        Read a file from the device.

        Args:
            ser: Serial connection object
            filename: Name of the file to read

        Returns:
            File contents as bytes
        """
        try:
            self.cmd_start()

            validate_filename(filename)

            command = f"$$$READ_FILE$$${filename}\n"
            self.send_buffer(command)

            # First response should contain file size and hash
            success, info = self.wait_for_response()
            if not success:
                raise SerialCommandError(f"Failed to get file info: {info}")

            try:
                size_str, expected_hash = info.split(',')
                file_size = int(size_str)
            except ValueError:
                raise SerialCommandError(f"Invalid file info received: {info}")

            if file_size > MAX_FILE_SIZE:
                raise SerialCommandError(f"File too large ({file_size} bytes)")

            # Read the file data in chunks
            data = bytearray()
            chunk_size = 1024

            self.serial_interface.block_serial = True
            while len(data) < file_size:
                chunk = self.serial_interface.serial_conn.read(min(chunk_size, file_size - len(data)))
                if not chunk:
                    raise SerialCommandError("Timeout reading file data")
                data.extend(chunk)

                # Send chunk acknowledgment
                self.serial_interface.serial_conn.write(b"OK\n")
                self.serial_interface.serial_conn.flush()
            self.serial_interface.block_serial = False

            # Verify file hash
            received_hash = hashlib.md5(data).hexdigest()
            if received_hash != expected_hash:
                raise SerialCommandError("File hash mismatch")

            # Wait for final OK
            success, message = self.wait_for_response()

            if not success:
                raise SerialCommandError(f"Error after reading file: {message}")

            self.cmd_end()
            return bytes(data)

        except (serial.SerialException, FileValidationError) as e:
            self.cmd_end()
            raise SerialCommandError(str(e))
        except Exception as e:
            self.cmd_end()
            raise SerialCommandError(f"Error reading file: {str(e)}")

    def list_files(self) -> List[Tuple[str, int]]:
        """
        Get list of files and their sizes on the device.

        Args:
            ser: Serial connection object

        Returns:
            List of tuples containing (filename, size)
        """
        try:
            self.cmd_start()

            command = "$$$LIST_FILES$$$\n"
            self.send_buffer(command)

            success, resp = self.wait_for_response(waitEnd=True)
            if not success:
                raise SerialCommandError(f"Failed to list files: {resp}")

            files = []
            if len(resp) > 0:
                if '!!LIST!!' in resp[0]:
                    list = resp[1:]
                    for entry in list:
                        try:
                            fname, size_str = entry.split(',')
                            #fname = fname[1:] # was a helloesp bug
                            files.append((fname, int(size_str)))
                        except ValueError:
                            raise SerialCommandError(f"Invalid file entry format: {entry}")

                else:
                    raise SerialCommandError(f"Wrong incipit cmd: {resp[0]}")

            self.cmd_end()
            return files

        except serial.SerialException as e:
            print_err("list_files", e)
            self.cmd_end()
            raise SerialCommandError(f"Serial communication error: {str(e)}")
        except Exception as e:
            print_err("list_files", e)
            self.cmd_end()
            raise SerialCommandError(f"Error listing files: {str(e)}")

    def execute_command(self, command: str) -> Tuple[bool, str]:
        """
        Execute a generic command on the device.

        Args:
            ser: Serial connection object
            command: Command string to execute (without $$$CMD$$$ prefix)

        Returns:
            Tuple of (success: bool, response: str)
            success indicates if command executed successfully
            response contains the command output or error message
        """

        try:
            self.cmd_start()

            # Format command with proper prefix and termination
            formatted_command = f"$$$CMD$$${command}\n"

            # Send command
            self.send_buffer(formatted_command)

            # Wait for and parse response
            success, response = self.wait_for_response()

            if not success:
                self.cmd_end()
                raise SerialCommandError(f"Command failed: {response}")

            # Parse response - assuming similar format to LIST_FILES
            # where response is in format "status:message"
            if False:
                split = response.split(':')
                if len(split) != 2:
                    raise SerialCommandError(f"Invalid response format: {response}")
                return True, split[1]
            else:  # simple response output
                print("execute_command response: " + response)
                self.cmd_end()
                return True, response

        except serial.SerialException as e:
            cmd_end(ser)
            raise SerialCommandError(f"Serial communication error: {str(e)}")
        except Exception as e:
            cmd_end(ser)
            print(f"Error executing command: {str(e)}")
            raise e

    def delete_file(self, filename: str) -> Tuple[bool, str]:
        """
        Delete a file from the device.

        Args:
            ser: Serial connection object
            filename: Name of the file to delete

        Returns:
            Tuple of (success, message)
        """
        try:
            self.cmd_start()

            validate_filename(filename)

            command = f"$$$DELETE_FILE$$${filename}\n"
            self.send_buffer(command)

            ok, resp = self.wait_for_response()

            self.cmd_end()

            return ok, resp

        except (serial.SerialException, FileValidationError) as e:
            self.cmd_end()
            raise SerialCommandError(str(e))
        except Exception as e:
            self.cmd_end()
            raise SerialCommandError(f"Error deleting file: {str(e)}")

    @staticmethod
    def _contains_alphanumeric(text: str) -> bool:
        """Verifica se il testo contiene caratteri alfanumerici."""
        return any(c.isalnum() for c in text)

    def _decode_data(self, data: bytes) -> str:
        """Decodifica i dati binari in testo."""
        try:
            return data.decode('utf8')
        except:
            return self._safe_decode(data)

    @staticmethod
    def _safe_decode(data: bytes) -> str:
        """Decodifica sicura dei dati binari."""
        try:
            return ''.join(chr(b) if 32 <= b <= 126 else f'\\x{b:02x}' for b in data)
        except:
            return ''