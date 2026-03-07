on run
	set sourceFolder to choose folder with prompt "Select the folder containing .doc files to convert:"
	set fileList to getFileNames(sourceFolder)

	tell application "Microsoft Word"
		activate
		repeat with aFile in fileList
			set fileAlias to (sourceFolder as text) & aFile

			if fileAlias ends with ".doc" then
				set newPath to (text 1 thru -5 of fileAlias) & ".docx"
				open (fileAlias as alias)
				save as active document file name newPath file format format document
				close active document saving no
			end if
		end repeat
	end tell
	display dialog "Batch conversion complete!"
end run

on getFileNames(sourceFolder)
	tell application "System Events"
		return name of every file of sourceFolder whose name extension is "doc"
	end tell
end getFileNames
