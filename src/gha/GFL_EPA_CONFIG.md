# Sample

## Single Account (Legacy/Standard)

- Looks like:
    ```json
    {
        "USER_UID": "1234567",
        "SERVER_KEY": "M4A1",
        "MACRO_LOOPS": 9999,
        "MISSIONS_PER_RETIRE": 10,
        "TEAMS": [
            {
                "TEAM_ID": 1,
                
                "FAIRY_ID": 12345,
                
                "GUNS": [
                    {
                        "id": 555555555,
                        "life": 113
                    },
                    {
                        "id": 555555555,
                        "life": 54
                    },
                    {
                        "id": 555555555,
                        "life": 115
                    },
                    {
                        "id": 555555555,
                        "life": 119
                    },
                    {
                        "id": 555555555,
                        "life": 49
                    }
                ]
            },
            {
                "TEAM_ID": 2,
                
                "FAIRY_ID": 12345,
                
                "GUNS": [
                    {
                        "id": 555555555,
                        "life": 61
                    },
                    {
                        "id": 555555555,
                        "life": 110
                    },
                    {
                        "id": 555555555,
                        "life": 132
                    },
                    {
                        "id": 555555555,
                        "life": 30
                    },
                    {
                        "id": 555555555,
                        "life": 42
                    }
                ]
            }
        ]
    }
    ```
- Input as:
    ```json
    { "USER_UID": "1234567", "SERVER_KEY": "M4A1", "MACRO_LOOPS": 9999, "MISSIONS_PER_RETIRE": 10, "TEAMS": [ { "TEAM_ID": 1, "FAIRY_ID": 12345, "GUNS": [ { "id": 555555555, "life": 113 }, { "id": 555555555, "life": 54 }, { "id": 555555555, "life": 115 }, { "id": 555555555, "life": 119 }, { "id": 555555555, "life": 49 } ] }, { "TEAM_ID": 2, "FAIRY_ID": 12345, "GUNS": [ { "id": 555555555, "life": 61 }, { "id": 555555555, "life": 110 }, { "id": 555555555, "life": 132 }, { "id": 555555555, "life": 30 }, { "id": 555555555, "life": 42 } ] } ] }
    ```