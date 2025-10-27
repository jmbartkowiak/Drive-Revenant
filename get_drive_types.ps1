# get_drive_types.ps1
# PowerShell script to get drive types

Get-CimInstance -ClassName Win32_LogicalDisk | ForEach-Object {
    $logicalDisk = $_
    $partition = Get-Partition -DriveLetter $logicalDisk.DeviceID.Trim(':')
    if ($partition) {
        $physicalDisk = Get-Disk -Number $partition.DiskNumber
        $friendlyName = $physicalDisk.FriendlyName
        $model = $physicalDisk.Model
        $mediaType = 'Unknown'
        
        # Determine type based on FriendlyName, Model, and Manufacturer
        $diskString = ($friendlyName + ' ' + $model + ' ' + $physicalDisk.Manufacturer).ToUpper()
        
        # Check for SSD indicators first
        if ($diskString -match 'NVME|SSD|SOLID STATE|M\.2|FLASH') {
            $mediaType = 'SSD'
        } 
        # Check for specific external SSD manufacturers/models
        elseif ($diskString -match 'SABRENT') {
            # Sabrent is known for external SSDs, especially if it's USB-connected
            if ($physicalDisk.BusType -eq 'USB') {
                $mediaType = 'SSD'
            } else {
                $mediaType = 'HDD'
            }
        }
        # Check for HDD indicators
        elseif ($diskString -match 'HDD|HARD DISK|SCSI|WDC|TOSHIBA|GAME DRIVE') {
            $mediaType = 'HDD'
        } 
        # Check for removable media
        elseif ($diskString -match 'SDXC|CARD|CARDREADER') {
            $mediaType = 'Removable'
        } 
        # For external drives that don't match patterns, use heuristics
        else {
            if ($logicalDisk.DriveType -eq 3) {
                # For fixed drives, check if it's USB-connected (likely external SSD)
                if ($physicalDisk.BusType -eq 'USB') {
                    $mediaType = 'SSD'  # Default external USB drives to SSD
                } else {
                    $mediaType = 'HDD'  # Default internal drives to HDD
                }
            } else {
                $mediaType = 'Unknown'
            }
        }
    } else {
        $mediaType = 'Unknown'
        $friendlyName = ''
        $model = ''
    }
    
    [PSCustomObject]@{
        DeviceID  = $logicalDisk.DeviceID
        DriveType = $logicalDisk.DriveType
        MediaType = $mediaType
        FriendlyName = $friendlyName
        Model = $model
    }
} | ConvertTo-Json