import time
from typing import Optional, Tuple, List
import serial


class SerialCommandError(Exception):
    """Custom exception for serial command errors"""
    pass


def wait_for_response(ser: serial.Serial, timeout: float = 2.0) -> Tuple[bool, str]:
    """
    Wait for and parse response from device.

    Args:
        ser: Serial connection object
        timeout: Maximum time to wait for response in seconds

    Returns:
        Tuple of (success, message)
    """
    start_time = time.time()
    response = ""

    while (time.time() - start_time) < timeout:
        if ser.in_waiting:
            line = ser.readline().decode('utf-8').strip()
            if line.startswith("OK:"):
                return True, line[3:].strip()
            elif line.startswith("ERROR:"):
                return False, line[6:].strip()
        time.sleep(0.1)

    raise SerialCommandError("Timeout waiting for response")


def write_file(ser: serial.Serial, filename: str, data: bytes) -> Tuple[bool, str]:
    """
    Write data to a file on the device.

    Args:
        ser: Serial connection object
        filename: Name of the file to write
        data: Binary data to write to the file

    Returns:
        Tuple of (success, message)
    """
    try:
        # Send command with filename and size
        command = f"$$$WRITE_FILE$$${filename},{len(data)}\n"
        ser.write(command.encode('utf-8'))
        ser.flush()

        # Small delay to ensure device is ready
        time.sleep(0.1)

        # Send file data
        ser.write(data)
        ser.flush()

        # Wait for response
        return wait_for_response(ser)

    except serial.SerialException as e:
        raise SerialCommandError(f"Serial communication error: {str(e)}")
    except Exception as e:
        raise SerialCommandError(f"Error writing file: {str(e)}")


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
        command = f"$$$READ_FILE$$${filename}\n"
        ser.write(command.encode('utf-8'))
        ser.flush()

        # First response should be file size
        success, size_str = wait_for_response(ser)
        if not success:
            raise SerialCommandError(f"Failed to get file size: {size_str}")

        try:
            file_size = int(size_str)
        except ValueError:
            raise SerialCommandError(f"Invalid file size received: {size_str}")

        # Read the file data
        data = ser.read(file_size)
        if len(data) != file_size:
            raise SerialCommandError(f"Received {len(data)} bytes, expected {file_size}")

        # Wait for final OK
        success, message = wait_for_response(ser)
        if not success:
            raise SerialCommandError(f"Error after reading file: {message}")

        return data

    except serial.SerialException as e:
        raise SerialCommandError(f"Serial communication error: {str(e)}")
    except Exception as e:
        raise SerialCommandError(f"Error reading file: {str(e)}")


def list_files(ser: serial.Serial) -> List[str]:
    """
    Get list of files on the device.

    Args:
        ser: Serial connection object

    Returns:
        List of filenames
    """
    try:
        command = "$$$LIST_FILES$$$\n"
        ser.write(command.encode('utf-8'))
        ser.flush()

        success, files_str = wait_for_response(ser)
        if not success:
            raise SerialCommandError(f"Failed to list files: {files_str}")

        return files_str.split(',')

    except serial.SerialException as e:
        raise SerialCommandError(f"Serial communication error: {str(e)}")
    except Exception as e:
        raise SerialCommandError(f"Error listing files: {str(e)}")


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
        command = f"$$$DELETE_FILE$$${filename}\n"
        ser.write(command.encode('utf-8'))
        ser.flush()

        return wait_for_response(ser)

    except serial.SerialException as e:
        raise SerialCommandError(f"Serial communication error: {str(e)}")
    except Exception as e:
        raise SerialCommandError(f"Error deleting file: {str(e)}")


# Example usage:
if __name__ == "__main__":
    # Example of how to use the functions
    try:
        # Open serial connection
        ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=1)

        # Write a file
        with open('test.txt', 'rb') as f:
            data = f.read()
            success, msg = write_file(ser, 'test.txt', data)
            print(f"Write file: {msg}")

        # List files
        files = list_files(ser)
        print(f"Files on device: {files}")

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