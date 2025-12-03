// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract AttendanceLogger {

    struct Attendance {
        bytes32 idHash;
        uint256 date;
        bool isPresent;
        bytes32 reasonHash; // reason disimpan dalam bentuk hash
        string name;
    }

    mapping(bytes32 => mapping(uint256 => Attendance)) public records;

    event Log(
        bytes32 indexed student,
        uint256 indexed date,
        bool present,
        bytes32 reasonHash,
        string name
    );

    function logAttendance(
        bytes32 idHash,
        uint256 date,
        bool isPresent,
        bytes32 reasonHash,  // sudah di-hash dari FE/BE
        string memory name
    ) external {
        require(records[idHash][date].idHash == bytes32(0), "Already Exists");

        records[idHash][date] = Attendance(
            idHash,
            date,
            isPresent,
            reasonHash,
            name
        );

        emit Log(idHash, date, isPresent, reasonHash, name);
    }

    // verify hanya mengembalikan hash, bukan string asli
    function verifyAttendance(
        bytes32 idHash,
        uint256 date
    ) external view returns (
        bool present,
        bytes32 reasonHash,
        string memory name
    ) {
        Attendance memory a = records[idHash][date];
        if (a.idHash == bytes32(0)) {
            return (false, bytes32(0), "");
        }

        return (a.isPresent, a.reasonHash, a.name);
    }
}
