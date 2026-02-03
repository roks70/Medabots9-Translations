## Disclosure
Just to be upfront, the initial story translation after Omnija and Sotaeko's work was made using DeepL's translations. This was initially machine translated and then cleaned up by me.  
**DLC** works with the english patch. **Update** .cia does not fully work with the english patch since it'll overwrite some files I'm modifying. I translated with the base game, applying the update will likely cause unexpected behavior.  
**Female protagonist** by Sotaeko and Omnija works with the english patch.

## Credit
Credit for starting and doing the essential gameplay elements:  
Omnija - Translator, Artist, ROM Hacking  
Sotaeko - Translator, Artist, Editor, Community Management  
Original repository - [Medarot-9-3ds-Translations](https://github.com/Omnija/Medarot-9-3ds-Translations/tree/master)  
[Medabots discord](https://discord.gg/CqusJ7fbGG) - for all the helpful clarifications/banter

## Instructions
For anyone who is might be trying to get this to work on an emulator. This works for me,

1. Download [Azahar plus](https://github.com/AzaharPlus/AzaharPlus/releases), no aes_keys.txt needed to install the .cia
2. Download the .cia for the medabots game somewhere
3. Download the files from the Medabots9-Translations repository
4. Open Azahar.exe
5. Install Medabots9 .cia game/file (File -> Install CIA... -> Find your .cia file)
6. Right click on the game -> Open -> Mods Location, it should take you to something like this ...\AppData\Roaming\AzaharPlus\load\mods\0004000000174F00
7. Make a romfs and exefs folder inside the 0004000000174F00 folder
8. Add the exefs and romfs folders inside the data folder (from the repository download in step 3.) into the folder structure of the mod 0004000000174F00 folder
9. **If you are using KBT do not add the exefs files. You can skip the exefs stuff, those only work for KWG**

It should end up looking something like this for the exefs folder:

<img width="815" height="285" alt="image" src="https://github.com/user-attachments/assets/d672f876-1058-4d65-9b84-fbebc63146c2" />

The banner.bnr is special, it just goes into the exefs folder (no extra folder).

for the romfs folder,

<img width="671" height="353" alt="image" src="https://github.com/user-attachments/assets/eab66efe-528e-479f-a04f-7d92523a3ce0" />

This allows the modded files to be used directly from the emulator. Much easier than extracting/rebuilding every time.

## Updates
In the python folder is the **M9-translations.csv** where the japanese, english, and the file that the japanese came from. Currently these are what's used to populate the rest of the romfs/story/spt files. It is unpolished and needs more refining. You can directly update the .spt file (in notepad++ or your choice of editor, just make sure you don't remove the nulls/other characters) and upload it in the repository. The translation was through DeepL so it definitely doesn't have the full Medabots context.

I included the **populate-spt-files.py** script for populating the original .spt files (in **docs/spt-orig.zip**) en masse. I'll be updating when I can now, but if you see things like "pretty-pline" (you can search in the .csv to see the original japanese and try to dechiper it) that's actually the medabot Pretty Prime. Let me know where you see translation issues like that and I'll be able to update at some point (or you can upload the file).

## Progress
Story (story/spt) - quality checked all story lines.  
Battle (battle/spt) - tutorials 1 and 2 are quality checked. The other aren't used.  
Help/Info (mdr/spt) - ~900 files. This seems to be the medawatch files which includes medaparts, memos, skill descriptions, 3 tutorials quality checked. Translations don't break the game but look rather ugly until quality checked/formatted.  
Internal Data (param) - this is where the medapart names/values live but it is binary data so a bit harder to edit manually without breaking something.  

