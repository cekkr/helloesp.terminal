import time
import os
from typing import Optional, Tuple, List
import serial
import hashlib
from main import *

from generalFunctions import *

class SerialCommandError(Exception):
    """Custom exception for serial command errors"""
    pass


class FileValidationError(Exception):
    """Custom exception for file validation errors"""
    pass


MAX_FILENAME_LENGTH = 255
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB


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


def wait_for_response(ser: serial.Serial = None, timeout: float = 5, serInt : SerialInterface = None) -> Tuple[bool, str]:
    """
    Wait for and parse response from device, handling info/warning/error logs.

    Args:
        ser: Serial connection object
        timeout: Maximum time to wait for response in seconds

    Returns:
        Tuple of (success, message)
    """

    if serInt is not None:
        ser = serInt.serial_conn

    thisLine = ""
    start_time = time.time()
    while (time.time() - start_time) < timeout or timeout == -1:
        if ser.in_waiting:
            try:
                data = ser.readline()
                #print("serial read data: ", data)
                line = safe_decode(data)

                if serInt is not None:
                    serInt.update_tracing(line)
            except Exception as e:
                print("Debug read exception: ", data)
                raise e

            thisLine += line

        if '\n' in thisLine or (len(thisLine) > 0 and (time.time() - start_time) > 0.1):
            line = thisLine

            esp_tag = parse_esp32_log(line)

            # Handle different log levels while continuing to wait for actual response
            if esp_tag is not None:
                line = esp_tag['message']
            elif line.startswith('\x1b'):
                try:
                    log_level, message = line.split(":", 1)
                    print(f"[{log_level}] {message.strip()}")
                    #line = message.strip()
                except Exception as e:
                    print("Received void")

            if esp_tag:
                print(f"[{esp_tag['level']}] {esp_tag['message']}")
            else:
                print(line)

            # Process actual responses
            if line.startswith("OK:"):
                ser.flush()
                return True, line[3:].strip()
            elif line.startswith("ERROR:"):
                ser.flush()
                return False, line[6:].strip()
            else:
                spl = thisLine.split('\n')
                if len(spl) > 1:
                    thisLine = spl[1]
                else:
                    thisLine = ""

                ser.flush()

        time.sleep(0.01)

    raise SerialCommandError("Timeout waiting for response")


def send_buffer(ser: serial.Serial, buffer, ping=True):
    if ping:
        ser.write("$$$PING$$$\n".encode('utf8'))
        ser.flush()
        success, msg = wait_for_response(ser)

        if not success:
            print("Ping unsuccessful: " + msg)
        else:
            print("PONG!")

    ser.write(buffer.encode('utf8'))
    ser.flush()

def write_file(serInterface: SerialInterface, filename: str, data: bytes) -> Tuple[bool, str]:
    """Write data to device with chunk verification."""

    ser = serInterface.serial_conn

    try:
        validate_filename(filename)
        if not validate_file_size(data):
            return False, f"Invalid file size (max {MAX_FILE_SIZE} bytes)"

        file_hash = hashlib.md5(data).hexdigest()
        if not check_existing_file(ser, filename, len(data)):
            return False, "File exists with same size"

        # Inizia trasferimento
        success, response = send_write_command(ser, filename, len(data), file_hash)
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
            send_buffer(ser, command, ping=False)

            success, message = wait_for_response(ser)
            if not success:
                return False, f"Chunk prep failed: {message}"

            print("Ready for chunk: ", message)

            # Invia chunk
            ser.write(chunk)
            ser.flush()

            # Verifica ricezione
            success, message = wait_for_response(ser)
            if not success:
                return False, f"Chunk verification failed: {message}"
            else:
                print("Chunk sent: ", message)

        # Verifica finale
        command = "$$$VERIFY_FILE$$$\n"
        send_buffer(ser, command.encode('utf8'))
        return wait_for_response(ser)

    except Exception as e:
        return False, f"Transfer error: {str(e)}"


def validate_file_size(data: bytes) -> bool:
    """Validate file size constraints."""
    return 0 < len(data) <= MAX_FILE_SIZE


def check_existing_file(ser: serial.Serial, filename: str, size: int) -> bool:
    """Check if file exists with same size."""
    command = f"$$$CHECK_FILE$$${filename}\n"
    send_buffer(ser, command)

    success, message = wait_for_response(ser)
    if success:
        try:
            existing_size = int(message.split(':')[0])
            return existing_size != size
        except ValueError:
            return True
    return True


def send_write_command(ser: serial.Serial, filename: str, size: int, file_hash: str) -> bool:
    """Send initial write command."""
    command = f"$$$WRITE_FILE$$${filename},{size},{file_hash}\n"
    send_buffer(ser, command)

    success, message = wait_for_response(ser)
    return success, message

def read_file(ser: serial.Serial, filename: str) -> bytes:
    """
    Read a file from the device.

    Args:
        ser: Serial connection object
        filename: Name of the file to read

    Returns:
        File contents as bytes
    """
    try:
        validate_filename(filename)

        command = f"$$$READ_FILE$$${filename}\n"
        send_buffer(ser, command)

        # First response should contain file size and hash
        success, info = wait_for_response(ser)
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

        while len(data) < file_size:
            chunk = ser.read(min(chunk_size, file_size - len(data)))
            if not chunk:
                raise SerialCommandError("Timeout reading file data")
            data.extend(chunk)

            # Send chunk acknowledgment
            ser.write(b"OK\n")
            ser.flush()

        # Verify file hash
        received_hash = hashlib.md5(data).hexdigest()
        if received_hash != expected_hash:
            raise SerialCommandError("File hash mismatch")

        # Wait for final OK
        success, message = wait_for_response(ser)
        if not success:
            raise SerialCommandError(f"Error after reading file: {message}")

        return bytes(data)

    except (serial.SerialException, FileValidationError) as e:
        raise SerialCommandError(str(e))
    except Exception as e:
        raise SerialCommandError(f"Error reading file: {str(e)}")


def list_files(ser: serial.Serial) -> List[Tuple[str, int]]:
    """
    Get list of files and their sizes on the device.

    Args:
        ser: Serial connection object

    Returns:
        List of tuples containing (filename, size)
    """
    try:
        command = "$$$LIST_FILES$$$\n"
        send_buffer(ser, command)

        success, files_str = wait_for_response(ser)
        if not success:
            raise SerialCommandError(f"Failed to list files: {files_str}")

        split = files_str.split(':')
        files_str = split[1]

        # Parse filename,size pairs
        files = []
        for entry in files_str.split(';'):
            if entry:
                try:
                    fname, size_str = entry.split(',')
                    files.append((fname, int(size_str)))
                except ValueError:
                    raise SerialCommandError(f"Invalid file entry format: {entry}")

        return files

    except serial.SerialException as e:
        raise SerialCommandError(f"Serial communication error: {str(e)}")
    except Exception as e:
        raise SerialCommandError(f"Error listing files: {str(e)}")


def execute_command(serInt: SerialInterface, command: str) -> Tuple[bool, str]:
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

    ser = serInt.serial_conn

    try:
        # Format command with proper prefix and termination
        formatted_command = f"$$$CMD$$${command}\n"

        # Send command
        send_buffer(ser, formatted_command)

        # Wait for and parse response
        success, response = wait_for_response(serInt=serInt)
        if not success:
            raise SerialCommandError(f"Command failed: {response}")

        # Parse response - assuming similar format to LIST_FILES
        # where response is in format "status:message"
        if False:
            split = response.split(':')
            if len(split) != 2:
                raise SerialCommandError(f"Invalid response format: {response}")
            return True, split[1]
        else: # simple response output
            print(response)
            return True, response

    except serial.SerialException as e:
        raise SerialCommandError(f"Serial communication error: {str(e)}")
    except Exception as e:
        raise SerialCommandError(f"Error executing command: {str(e)}")

def delete_file(ser: serial.Serial, filename: str) -> Tuple[bool, str]:
    """
    Delete a file from the device.

    Args:
        ser: Serial connection object
        filename: Name of the file to delete

    Returns:
        Tuple of (success, message)
    """
    try:
        validate_filename(filename)

        command = f"$$$DELETE_FILE$$${filename}\n"
        send_buffer(ser, command)

        return wait_for_response(ser)

    except (serial.SerialException, FileValidationError) as e:
        raise SerialCommandError(str(e))
    except Exception as e:
        raise SerialCommandError(f"Error deleting file: {str(e)}")


# Example usage:
if __name__ == "__main__":
    # Example of how to use the functions
    try:
        # Open serial connection
        ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)

        # List existing files
        files = list_files(ser)
        print("Files on device:")
        for fname, size in files:
            print(f"  {fname}: {size} bytes")

        # Write a file
        with open('test.txt', 'rb') as f:
            data = f.read()
            success, msg = write_file(ser, 'test.txt', data)
            print(f"Write file: {msg}")

        # Read the file back
        data = read_file(ser, 'test.txt')
        print(f"Read {len(data)} bytes")

        # Delete the file
        success, msg = delete_file(ser, 'test.txt')
        print(f"Delete file: {msg}")

    except SerialCommandError as e:
        print(f"Command error: {str(e)}")
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        ser.close()